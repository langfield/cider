#!/usr/bin/env python
# coding:utf-8
""" Start a UDP NAT traversal client. """
import sys
import time
import socket
import struct
import optparse
from typing import Tuple, Optional
from threading import Event, Thread, Timer

import stun

# pylint: disable=invalid-name

FullCone = "Full Cone"  # 0
RestrictNAT = "Restrict NAT"  # 1
RestrictPortNAT = "Restrict Port NAT"  # 2
SymmetricNAT = "Symmetric NAT"  # 3
UnknownNAT = "Unknown NAT"  # 4
NATTYPE = (FullCone, RestrictNAT, RestrictPortNAT, SymmetricNAT, UnknownNAT)


def bytes2addr(bytes_address: bytes) -> Tuple[Tuple[str, int], int]:
    """Convert a hash to an address pair."""
    if len(bytes_address) != 8:
        raise ValueError("invalid bytes_address")
    host = socket.inet_ntoa(bytes_address[:4])
    port = struct.unpack("H", bytes_address[-4:-2])[
        0
    ]  # unpack returns a tuple even if it contains exactly one item
    nat_type_id = struct.unpack("H", bytes_address[-2:])[0]
    target = (host, port)
    return target, nat_type_id


class Client:
    """ The UDP client for interacting with the server and other Clients. """

    def __init__(self) -> None:
        try:
            master_ip = "127.0.0.1" if sys.argv[1] == "localhost" else sys.argv[1]
            self.master = (master_ip, int(sys.argv[2]))
            self.pool = sys.argv[3].strip()
            self.sockfd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.target: Tuple[str, int] = ("", 0)
            self.periodic_running = False
            self.peer_nat_type = ""
        except (IndexError, ValueError):
            print((sys.stderr, "usage: %s <host> <port> <pool>" % sys.argv[0]))
            sys.exit(65)

    def request_for_connection(self, nat_type_id: int = 0) -> None:
        """ Send a request to the server for a connection. """
        self.sockfd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        msg = (self.pool + " {0}".format(nat_type_id)).encode("ascii")
        self.sockfd.sendto(msg, self.master)
        data, _addr = self.sockfd.recvfrom(len(self.pool) + 3)
        if data.decode("ascii") != "ok " + self.pool:
            print((sys.stderr, "unable to request!"))
            sys.exit(1)
        self.sockfd.sendto("ok".encode("ascii"), self.master)
        sys.stderr = sys.stdout
        print(
            (
                sys.stderr,
                "request sent, waiting for partner in pool '%s'..." % self.pool,
            )
        )
        data, _addr = self.sockfd.recvfrom(8)

        self.target, peer_nat_type_id = bytes2addr(data)
        print((self.target, peer_nat_type_id))
        self.peer_nat_type = NATTYPE[peer_nat_type_id]
        print(
            (
                sys.stderr,
                "connected to {1}:{2}, its NAT type is {0}".format(
                    self.peer_nat_type, *self.target
                ),
            )
        )

    def recv_msg(self, sock, event: Optional[Event] = None, is_restrict: bool = False):
        """ Receive message callback. """
        if is_restrict and event:
            while True:
                data, addr = sock.recvfrom(1024)
                data = data.decode("ascii")
                if self.periodic_running:
                    print("periodic_send is alive")
                    self.periodic_running = False
                    event.set()
                    print(
                        "received msg from target,"
                        "periodic send cancelled, chat start."
                    )
                if addr in (self.target, self.master):
                    sys.stdout.write(data)
                    if data == "punching...\n":
                        sock.sendto("end punching\n".encode("ascii"), addr)
        else:
            while True:
                data, addr = sock.recvfrom(1024)
                data = data.decode("ascii")
                if addr in (self.target, self.master):
                    print("%.10f:" % time.time(), data)
                    # sys.stdout.write(data)
                    if data == "punching...\n":  # peer是restrict
                        sock.sendto("end punching".encode("ascii"), addr)

    def send_msg(self, sock):
        """ Send message callback. """
        while True:
            data = sys.stdin.readline()
            print("%.10f:" % time.time(), data)
            data_bytes = data.encode("ascii")
            sock.sendto(data_bytes, self.target)

    @staticmethod
    def start_working_threads(
        send, recv, sock, event: Optional[Event], is_restrict: bool
    ) -> None:
        """ Start the send and recv threads. """
        ts = Thread(target=send, args=(sock,))
        ts.setDaemon(True)
        ts.start()
        if event:
            event.wait()
        tr = Thread(target=recv, args=(sock, event, is_restrict))
        tr.setDaemon(True)
        tr.start()

    def chat_fullcone(self) -> None:
        """ Start chat for a client behind a FullCone NAT. """
        self.start_working_threads(
            self.send_msg, self.recv_msg, self.sockfd, event=None, is_restrict=False
        )

    def chat_restrict(self) -> None:
        """ Start chat for a client behind a RestrictNAT. """

        cancel_event = Event()

        def send(count):
            self.sockfd.sendto("punching...\n".encode("ascii"), self.target)
            print(("UDP punching package {0} sent".format(count)))
            if self.periodic_running:
                Timer(0.5, send, args=(count + 1,)).start()

        self.periodic_running = True
        send(0)
        self.start_working_threads(
            self.send_msg,
            self.recv_msg,
            self.sockfd,
            event=cancel_event,
            is_restrict=True,
        )

    def chat_symmetric(self) -> None:
        """ Completely rely on relay server (TURN). """

        def send_msg_symm(sock):
            """ Send message callback. """
            while True:
                data = "msg " + sys.stdin.readline()
                sock.sendto(data.encode("ascii"), self.master)

        # pylint: disable=unused-argument
        def recv_msg_symm(sock, event: Optional[Event], is_restrict: bool) -> None:
            """ Receive message callback. """
            while True:
                data, addr = sock.recvfrom(1024)
                data = data.decode("ascii")
                if addr == self.master:
                    sys.stdout.write(data)

        self.start_working_threads(
            send_msg_symm, recv_msg_symm, self.sockfd, event=None, is_restrict=False
        )

    def main(self, test_nat_type: str = "") -> None:
        """
        nat_type是自己的nat类型
        peer_nat_type是从服务器获取的对方的nat类型
        选择哪种chat模式是根据nat_type来选择, 例如我这边的NAT设备是restrict, 那么我必须得一直向对方发包,
        我的NAT设备才能识别对方为"我已经发过包的地址". 直到收到对方的包, periodic发送停止
        """
        if not test_nat_type:
            nat_type, _, _ = self.get_nat_type()
        else:
            nat_type = test_nat_type  # 假装正在测试某种类型的NAT
        try:
            self.request_for_connection(nat_type_id=NATTYPE.index(nat_type))
        except ValueError:
            print(("NAT type is %s" % nat_type))
            self.request_for_connection(nat_type_id=4)  # Unknown NAT

        if UnknownNAT in (nat_type, self.peer_nat_type):
            print("Symmetric chat mode")
            self.chat_symmetric()
        if SymmetricNAT in (nat_type, self.peer_nat_type):
            print("Symmetric chat mode")
            self.chat_symmetric()
        elif nat_type == FullCone:
            print("FullCone chat mode")
            self.chat_fullcone()
        elif nat_type in (RestrictNAT, RestrictPortNAT):
            print("Restrict chat mode")
            self.chat_restrict()
        else:
            print("NAT type wrong!")

        while True:
            try:
                time.sleep(0.5)
            except KeyboardInterrupt:
                print("exit")
                sys.exit(0)

    @staticmethod
    def get_nat_type() -> Tuple[str, str, int]:
        """ Parses arguments and returns the NAT type. """
        parser = optparse.OptionParser(version=stun.__version__)
        parser.add_option(
            "-d",
            "--debug",
            dest="DEBUG",
            action="store_true",
            default=False,
            help="Enable debug logging",
        )
        parser.add_option(
            "-H", "--host", dest="stun_host", default=None, help="STUN host to use"
        )
        parser.add_option(
            "-P",
            "--host-port",
            dest="stun_port",
            type="int",
            default=3478,
            help="STUN host port to use (default: " "3478)",
        )
        parser.add_option(
            "-i",
            "--interface",
            dest="source_ip",
            default="0.0.0.0",
            help="network interface for client (default: 0.0.0.0)",
        )
        parser.add_option(
            "-p",
            "--port",
            dest="source_port",
            type="int",
            default=54320,
            help="port to listen on for client " "(default: 54320)",
        )
        (options, _args) = parser.parse_args()
        if options.DEBUG:
            stun.enable_logging()
        kwargs = dict(
            source_ip=options.source_ip,
            source_port=int(options.source_port),
            stun_host=options.stun_host,
            stun_port=options.stun_port,
        )
        nat_type, external_ip, external_port = stun.get_ip_info(**kwargs)
        print(("NAT Type:", nat_type))
        print(("External IP:", external_ip))
        print(("External Port:", external_port))
        return nat_type, external_ip, external_port


if __name__ == "__main__":
    c = Client()
    try:
        TEST_NAT_TYPE = NATTYPE[int(sys.argv[4])]  # 输入数字0,1,2,3
    except IndexError:
        TEST_NAT_TYPE = ""

    c.main(TEST_NAT_TYPE)