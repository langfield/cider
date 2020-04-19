/**
 * Copyright (c) 2020 Paul-Louis Ageneau
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

#include "juice/juice.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h> // for sleep

#define BUFFER_SIZE 4096

static juice_agent_t *agent2;

static void on_state_changed2(juice_agent_t *agent, juice_state_t state, void *user_ptr);

static void on_candidate1(juice_agent_t *agent, const char *sdp, void *user_ptr);

static void on_gathering_done2(juice_agent_t *agent, void *user_ptr);

static void on_recv2(juice_agent_t *agent, const char *data, size_t size, void *user_ptr);

const int write_sdp(char path[], const char *sdp);

const char * read_sdp(char path[]);

int test_connectivity() {
	juice_set_log_level(JUICE_LOG_LEVEL_DEBUG);

    printf("Max SDP string length: %d\n", JUICE_MAX_SDP_STRING_LEN);
    printf("Max SDP ADDRESS string length: %d\n", JUICE_MAX_ADDRESS_STRING_LEN);

	// Agent 2: Create agent
	juice_config_t config2;
	memset(&config2, 0, sizeof(config2));
	// config2.stun_server_host = "stun.l.google.com";
	// config2.stun_server_port = 19302;
	config2.cb_state_changed = on_state_changed2;
	config2.cb_gathering_done = on_gathering_done2;
	config2.cb_recv = on_recv2;
	config2.user_ptr = NULL;

	agent2 = juice_create(&config2);

    char* SDP1_PATH = "sdp1";
    char* SDP2_PATH = "sdp2";

    //+++++++++++DESCRIPTION EXCHANGE++++++++++++

    // Wait until SDPs have been copied between hosts.
    char dummy[20];
    printf("Confirm file 'sdp1' is in working directory: ");
    fgets(dummy, 20, stdin);

	// Agent 2: Read local description from stdin.
	char sdp1[JUICE_MAX_SDP_STRING_LEN];
    strcpy(sdp1, read_sdp(SDP1_PATH));
	printf("Local description 1:\n###\n%s\n###\n", sdp1);

    // Agent 2: Receive description from agent 1
    juice_set_remote_description(agent2, sdp1);

	// Agent 2: Generate local description
	char sdp2[JUICE_MAX_ADDRESS_STRING_LEN];
	juice_get_local_description(agent2, sdp2, JUICE_MAX_SDP_STRING_LEN);
	printf("Local description 2:\n###\n%s\n###\n", sdp2);

    // Wait until SDPs have been copied between hosts.
    printf("Confirm file 'sdp2' is in remote working directory: ");
    fgets(dummy, 20, stdin);
    write_sdp(SDP2_PATH, sdp2);

    //+++++++++++++++++++++++++++++++++++++++++++

	// Agent 2: Gather candidates (and send them to agent 1)
	juice_gather_candidates(agent2);
	sleep(2);

    printf("Confirm remote done gathering: ");
    fgets(dummy, 20, stdin);

	// -- Connection should be finished --

	// Check states
	bool success = juice_get_state(agent2) == JUICE_STATE_COMPLETED;

	// Retrieve addresses
	char local[JUICE_MAX_ADDRESS_STRING_LEN];
	char remote[JUICE_MAX_ADDRESS_STRING_LEN];
	if (success &= (juice_get_selected_addresses(agent2, local, JUICE_MAX_ADDRESS_STRING_LEN,
	                                             remote, JUICE_MAX_ADDRESS_STRING_LEN) == 0)) {
		printf("Local address  1: %s\n", local);
		printf("Remote address 1: %s\n", remote);
	}

	// Agent 2: destroy
	juice_destroy(agent2);

	// Sleep so we can check destruction went well
	sleep(2);

	if (success) {
		printf("Success\n");
		return 0;
	} else {
		printf("Failure\n");
		return -1;
	}
}

// Agent 2: on state changed
static void on_state_changed2(juice_agent_t *agent, juice_state_t state, void *user_ptr) {
	printf("State 2: %s\n", juice_state_to_string(state));

	if (state == JUICE_STATE_CONNECTED) {
		// Agent 2: on connected, send a message
		const char *message = "Hello from 2";
		juice_send(agent, message, strlen(message));
	}
}

// Agent 2: on local candidate gathered
static void on_candidate2(juice_agent_t *agent, const char *sdp, void *user_ptr) {
    char* SDP1_CANDIDATE_PATH = "sdp1_candidate";
    char* SDP2_CANDIDATE_PATH = "sdp2_candidate";

	printf("Candidate 2: %s\n", sdp);
    write_sdp(SDP2_CANDIDATE_PATH, sdp);

    // Agent 2: Wait until candidates have been copied.
    char dummy[20];
    printf("Confirm sdp1_candidate in working directory: ");
    fgets(dummy, 20, stdin);

    // Agent 2: Read SDP candidate from agent 1
	char sdp1_candidate[JUICE_MAX_ADDRESS_STRING_LEN];
    strcpy(sdp1_candidate, read_sdp(SDP1_CANDIDATE_PATH));

	// Agent 2: Receive it from agent 1
	juice_add_remote_candidate(agent2, sdp1_candidate);
}

// Agent 2: on local candidates gathering done
static void on_gathering_done2(juice_agent_t *agent, void *user_ptr) {
	printf("Gathering done 2\n");
	// juice_set_remote_gathering_done(agent2); // optional
}

// Agent 2: on message received
static void on_recv2(juice_agent_t *agent, const char *data, size_t size, void *user_ptr) {
	char buffer[BUFFER_SIZE];
	if (size > BUFFER_SIZE - 1)
		size = BUFFER_SIZE - 1;
	memcpy(buffer, data, size);
	buffer[size] = '\0';
	printf("Received 2: %s\n", buffer);
}
