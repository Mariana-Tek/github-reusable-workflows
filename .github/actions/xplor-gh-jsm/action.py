#!/usr/bin/env python3
import argparse
import os
import traceback

from lib.utils import str_to_bool
from main import main, COMMANDS

if __name__ == "__main__":
    cmd_list = [command.value for command in COMMANDS]
    # get the command first
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('command', type=str, choices=[c.value for c in COMMANDS], nargs='?',
                        default=COMMANDS.CREATE.value)
    args, remaining = parser.parse_known_args()

    #
    # actual argument parser
    parser = argparse.ArgumentParser(
        description="xplor-gh-jsm - GitHub Action to interact with Jira Service Management")
    parser.add_argument('command', type=str, choices=cmd_list, help=f'Command to execute')
    parser.add_argument('--pr-number', type=int, required=False,
                        help='GitHub pull request number to link with the issue')
    parser.add_argument('--template-key', type=str, required=True,
                        help='Jira issue key to be used as a template for cloning the request')

    if args.command == COMMANDS.CREATE.value or args.command == COMMANDS.CAN_PR_AUTHOR_BE_ASSIGNED.value:
        parser.add_argument('--pr-author-email', type=str, required=False,
                            help='Email of the PR author to be set as the reporter of the cloned request')

    if args.command == COMMANDS.CREATE.value:
        parser.add_argument('--pr-approver-email', type=str, required=False, action='append',
                            help='Emails of the PR approvers to be added to the description header.')

    if args.command == COMMANDS.MOVE_TO_DEPLOYED.value:
        parser.add_argument('--proof-url-list', type=str, required=True, action='append',
                            help='Json URLS to the proof of deployment')

    # optional arguments
    parser.add_argument('--jsm-user', type=str, help='Jira/JSM API user for authentication')
    parser.add_argument('--jsm-token', type=str, help='Jira/JSM API token for authentication')
    parser.add_argument('--pr-actor-email', type=str, required=False, help='PR actor email')
    parser.add_argument('--dry-run', type=str_to_bool, default=False,
                        help='Enable or disable dry run mode (default: False)')
    parser.add_argument('--debug', type=str_to_bool, default=False, help='Enable debug mode (default: False)')
    parser.add_argument('--graceful-exit', type=str_to_bool, help='Print errors instead of failing the action')
    args = parser.parse_args()

    if args.debug:
        for key, val in sorted(os.environ.items()):
            print(f"{key}={val}")

    try:
        main(args)
    except Exception as e:
        if args.graceful_exit:
            print('-------------- Exception occurred -----------')
            traceback.print_exc()  # This prints the full exception details
            print('---------------------------------------------')
            print("Graceful exit enabled, exiting with code 0")
            exit(0)
        else:
            raise e
