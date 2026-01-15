import os
import time
from enum import Enum

import requests
from decouple import config

from lib.commands import clone_request_by_key, move_to_deploying, move_to_deployed, cancel_older_pending_requests
from lib.gh_utils import GHUtils, gh_output_env_vars, ReleasePR
from lib.jira_jsm import JiraITSM
from lib.utils import parse_proof_of_success_url_line


class COMMANDS(Enum):
    CREATE = 'create-change-request'
    MOVE_TO_DEPLOYING = 'move-to-deploying'
    MOVE_TO_DEPLOYED = 'move-to-deployed'
    CANCEL_OLDER_PENDING = 'cancel-older-pending-requests'
    CAN_PR_AUTHOR_BE_ASSIGNED = 'can-pr-author-be-assigned'


def main(args):
    #
    #
    #
    def jira_instance_from_ticket_prefix(ticket):
        base_url = base_url_s if 'ITPOC' in ticket else base_url_p
        return JiraITSM(server=base_url, username=jsm_user, password=jsm_token, debug=_debug, dry_run=_dry_run)

    def debug_print(msg):
        if _debug:
            print(f"DEBUG: {msg}")

    jsm_user = config("JSM_USER", default=args.jsm_user)
    jsm_token = config("JSM_TOKEN", default=args.jsm_token)
    if not jsm_user or not jsm_token:
        raise Exception("JSM_USER and JSM_TOKEN are required.")

    _debug = config("JSM_DEBUG", default=args.debug, cast=bool)
    _dry_run = config("JSM_DRY_RUN", default=args.dry_run, cast=bool)
    base_url_p = config("JSM_BASE_URL", default="https://xplortechnologies.atlassian.net")
    base_url_s = config('JSM_SANDBOX_BASE_URL', default="https://xplortechnologies-sandbox-jsm.atlassian.net")

    gh = GHUtils()
    gh_output_env_vars(XPLOR_GH_JM=True)
    match COMMANDS(args.command):
        #
        case COMMANDS.CAN_PR_AUTHOR_BE_ASSIGNED:
            if not args.pr_author_email:
                raise Exception("pr_author_email is required for can-pr-author-be-assigned command")

            jsm = jira_instance_from_ticket_prefix(args.template_key)
            u = jsm.search_users(query=args.pr_author_email)
            if not u or len(u) == 0:
                raise Exception(f"pr_author_email '{args.pr_author_email}' not found in JSM users")

            can_assign = jsm.search_assignable_users_for_issues(query=args.pr_author_email,
                                                                project=jsm.project_key)
            if not can_assign:
                raise Exception(
                    f"pr_author_email '{args.pr_author_email}' cannot be assigned issues in project {jsm.project_key}")

            print(f"Nice! pr_author_email '{args.pr_author_email}' can be assigned issues in project {jsm.project_key}")
            exit(0)

        #
        case COMMANDS.CREATE:
            # For releases, PR_NUMBER may not be available - use ReleasePR instead
            if args.pr_number:
                pr = gh.get_pr(args.pr_number, skip_label_validation=True)
            else:
                # No PR number - this is likely a release deployment
                release_tag = os.getenv('GITHUB_REF_NAME', '').replace('refs/tags/', '')
                if not release_tag:
                    release_tag = os.getenv('GITHUB_REF', '').replace('refs/tags/', '')
                print(f"Creating JSM change request for release: {release_tag}")
                pr = gh.get_release_pr(release_tag=release_tag)
            
            jsm = jira_instance_from_ticket_prefix(args.template_key)

            # reporter
            reporter_account_id = None
            if args.pr_actor_email:
                u = jsm.search_users(query=args.pr_actor_email)
                if u and len(u) > 0:
                    reporter_account_id = u[0].accountId
                else:
                    debug_print(f"PR actor email '{args.pr_actor_email}' not found in JSM users")

            # author and assignee
            author_account_id = None
            assignee_account_id = None
            if args.pr_author_email:
                u = jsm.search_users(query=args.pr_author_email)
                if u and len(u) > 0:
                    author_account_id = u[0].accountId
                    can_assign = jsm.search_assignable_users_for_issues(query=args.pr_author_email,
                                                                        project=jsm.project_key)
                    if can_assign:
                        assignee_account_id = can_assign[0].accountId
                    else:
                        print(
                            f"NOTE: PR author email '{args.pr_author_email}' cannot be assigned issues in project {jsm.project_key}")
                else:
                    debug_print(f"PR author email '{args.pr_author_email}' not found in JSM users")

            # approvers
            approvers = []
            if args.pr_approver_email:
                for email in args.pr_approver_email:
                    u = jsm.search_users(query=email)
                    if u and len(u) > 0:
                        approvers.append(u[0].accountId)
                    else:
                        debug_print(f"PR approver email '{email}' not found in JSM users")

            clone_request_by_key(jsm,
                                 args.template_key,
                                 pr,
                                 reporter_account_id=reporter_account_id,
                                 author_account_id=author_account_id,
                                 assignee_account_id=assignee_account_id,
                                 approvers=approvers)
        #
        case COMMANDS.MOVE_TO_DEPLOYING:
            if args.pr_number:
                pr = gh.get_pr(args.pr_number)
                jsm = jira_instance_from_ticket_prefix(pr.issue_label)
                issue = jsm.customer_request(pr.issue_label)
            else:
                # For releases without PR, use template_key as the issue key
                # (assuming it was set to the created issue key from CREATE step)
                if not args.template_key:
                    raise Exception("TEMPLATE_KEY is required for move-to-deploying when PR_NUMBER is not available. "
                                  "For releases, provide the JSM issue key that was created for this release.")
                jsm = jira_instance_from_ticket_prefix(args.template_key)
                issue = jsm.customer_request(args.template_key)
                release_tag = os.getenv('GITHUB_REF_NAME', '').replace('refs/tags/', '')
                pr = gh.get_release_pr(release_tag=release_tag)
            move_to_deploying(issue, pr)
        #
        case COMMANDS.MOVE_TO_DEPLOYED:
            if args.pr_number:
                pr = gh.get_pr(args.pr_number)
                jsm = jira_instance_from_ticket_prefix(pr.issue_label)
                issue = jsm.customer_request(pr.issue_label)
            else:
                # For releases, we need the issue key
                if not args.template_key:
                    raise Exception("TEMPLATE_KEY is required for move-to-deployed when PR_NUMBER is not available. "
                                  "For releases, provide the JSM issue key that was created for this release.")
                jsm = jira_instance_from_ticket_prefix(args.template_key)
                # Use template_key as the issue key for releases (assuming it was set to the created issue key)
                issue = jsm.customer_request(args.template_key)
                release_tag = os.getenv('GITHUB_REF_NAME', '').replace('refs/tags/', '')
                pr = gh.get_release_pr(release_tag=release_tag)

            proof_data = []

            proof_attachment = None
            for url in args.proof_url_list:
                url, headers = parse_proof_of_success_url_line(url)
                if url:
                    proof_data.append(f"[{url}|{url}]")
                    try:
                        debug_print(f"Trying to fetch proof of deployment from {url} with headers {headers}")
                        response = requests.get(url, headers=headers, timeout=30)
                        response.raise_for_status()
                        content_type = response.headers.get('content-type', 'application/octet-stream')
                        filename = os.path.basename(url) or f'download-{int(time.time())}'
                        if _dry_run:
                            print(f"DRY-RUN: Would attach proof of deployment from {url} to issue {issue.key}")
                            print(f" - content_type: {content_type}")
                            print(f" - filename: {filename}")
                            proof_attachment = {'temporaryAttachmentId': 'dry-run-id', 'fileName': filename}
                        else:
                            file_content = response.content
                            proof_attachment = jsm.add_temporary_attachment(
                                file_content=file_content,
                                content_type=content_type,
                                filename=filename,
                            )
                            issue.update()
                    except requests.RequestException as e:
                        pass

            if not proof_attachment:
                raise Exception(f"At least one of the proof urls must be reachable to be attached to issue {issue.key}")

            move_to_deployed(issue, pr, "\n".join(proof_data), proof_attachment)

            # TODO: conditionally cancel older pending requests
            try:
                cancel_older_pending_requests(jsm, issue, pr, gh)
            except Exception as e:
                debug_print(f"DEBUG: Failed to cancel older pending requests: {e}")
                pass

        #
        case COMMANDS.CANCEL_OLDER_PENDING:
            if not args.pr_number:
                raise Exception("PR_NUMBER is required for cancel-older-pending-requests command. "
                              "This command cancels older pending JSM requests by finding them via the PR's issue label. "
                              "When publishing a release directly (not from a PR), PR_NUMBER may not be available.")
            pr = gh.get_pr(args.pr_number)
            jsm = jira_instance_from_ticket_prefix(pr.issue_label)
            issue = jsm.customer_request(pr.issue_label)
            cancel_older_pending_requests(jsm, issue, pr, gh)
