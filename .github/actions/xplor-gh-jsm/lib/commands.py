from datetime import timedelta
from time import sleep

from .gh_enums import IssueStatus, IssueTransition, as_list, IssueResolution
from .gh_utils import gh_output_env_vars, CustomPullRequest
from .utils import now_in_utc, compact_list_contains


def assert_issue_status(issue, current_status_names, accepted_status_names, target_state):
    current_status_names = as_list(current_status_names)
    accepted_status_names = as_list(accepted_status_names)
    #
    if not compact_list_contains(current_status_names, issue.fields.status.name):
        print(f"Issue {issue.key} is not in an acceptable status to '{target_state}': {issue.fields.status.name}")
        return False
    if compact_list_contains(accepted_status_names, issue.fields.status.name):
        print(f"Issue {issue.key} is already in an acceptable status: {issue.fields.status.name}")
        return False
    return True


def clone_request_by_key(jsm, template_key, pr,
                         reporter_account_id=None,
                         author_account_id=None,
                         assignee_account_id=None,
                         approvers=None):
    """Clone a request from a template and link it to a GitHub PR."""

    # description header
    header = [f"Pull Request #{pr.number} [{pr.html_url}|{pr.html_url}]"]
    if author_account_id:
        header.append(f"  Author: [~accountid:{author_account_id}]")
    else:
        header.append(f"  Author: {pr.user.login}")
    if approvers:
        for approver in approvers:
            header.append(f"  Approved by: [~accountid:{approver}]")
    else:
        approvers_list = pr.get_approvers()
        header.append(f"  Approved by: {approvers_list}")

    pr_title = pr.title or None
    pr_description = pr.body or None
    clone = jsm.clone_request(template_key, summary=pr_title,
                              header=f"{"\n".join(header)}\n----\n",
                              description=pr_description,
                              reporter=reporter_account_id,
                              assignee=assignee_account_id)
    if jsm.dry_run(f"clone {template_key}"):
        gh_output_env_vars(CREATED_ISSUE_KEY='DRY_RUN')
    else:
        if not hasattr(clone, 'key') or not clone.key:
            raise Exception(f"Failed to clone request {template_key}")
        gh_output_env_vars(CREATED_ISSUE_KEY=clone.key)

    # set planned start and end dates
    if not jsm.dry_run(f"set Planned_Start and Planned_End for cloned issue"):
        clone.update(Planned_Start=now_in_utc())
        clone.update(Planned_End=now_in_utc(timedelta(days=5)))

    # label the PR with the issue key
    if not jsm.dry_run(f"label PR #{pr.number} with cloned key (e.g. {jsm.project_key}-1234)"):
        pr.add_label(clone.key)

    status_str = IssueStatus.AWAITING_IMPLEMENTATION.value
    if not jsm.dry_run(f"transition cloned issue to '{status_str}'", f"add label '{status_str}' to PR #{pr.number}",
                       f"comment on PR #{pr.number} with cloned issue URL"):
        issue = jsm.customer_request(clone.key)
        pr.create_issue_comment(issue.browser_url)
        issue.transition_to([IssueTransition.NORMAL_CHANGE, IssueTransition.STANDARD_CHANGE], label='cloning')
        pr.add_label(IssueStatus.AWAITING_IMPLEMENTATION)  # issue.fields.status.name


def move_to_deploying(issue, pr):
    """Move the issue associated with the latest PR to 'deploying' state."""
    if not assert_issue_status(issue, IssueStatus.AWAITING_IMPLEMENTATION, IssueStatus.IMPLEMENTING, 'deploying'):
        return

    issue.transition_to(IssueTransition.IMPLEMENT, label=IssueStatus.IMPLEMENTING)

    if issue.dry_run(f"update actual_start date on {issue.key}", f"change labels on PR #{pr.number} to 'Implementing'"):
        return

    issue.update(Actual_Start=now_in_utc())
    pr.remove_label(IssueStatus.AWAITING_IMPLEMENTATION)
    pr.add_label(IssueStatus.IMPLEMENTING)


def move_to_deployed(issue, pr, proof_data, temporary_attachment):
    """Move the issue associated with the latest PR to 'deployed' state."""

    if not assert_issue_status(issue, IssueStatus.IMPLEMENTING, IssueStatus.COMPLETED, 'deployed'):
        return

    if issue.dry_run(f"move issue {issue.key} to 'deployed' state with proof data: {proof_data}"):
        return

    # not sure why but resolution notes cannot be set anymore during the transition
    if not issue.dry_run(f"update resolution notes and proof of success on {issue.key}"):
        issue.update(Resolution_Notes="Standard Change Template Approval")
        issue.update(Proof_Of_Success=proof_data)

    issue.transition_to(IssueTransition.COMPLETE, label=IssueStatus.COMPLETED,
                        Resolution=IssueResolution.SUCCESSFUL,
                        Attachment=[temporary_attachment["temporaryAttachmentId"]],
                        # Resolution_Notes="Standard Change Template Approval",
                        # Proof_Of_Success=proof_data,
                        )

    # check if the issue is in an acceptable status
    if not compact_list_contains([IssueStatus.COMPLETED.value], issue.fields.status.name):
        raise Exception(f"{issue.fields.status.name} cannot be moved to 'deployed' state.")

    issue.update(Actual_End=now_in_utc())
    pr.remove_label(IssueStatus.IMPLEMENTING)
    pr.add_label(IssueStatus.COMPLETED)

    # add attachment link to the Proof of Success field
    attachments = issue.fields.attachment
    if attachments:  # it should be at least one - the one we just added
        latest_attachment = sorted(attachments, key=lambda x: x.created, reverse=True)[0]
        attachment_link = f'[^ {latest_attachment.filename}]'  # Wiki markup for attachment link
        issue.update(Proof_of_Success=attachment_link, append=True)


def move_to_canceled(issue, pr, resolution_notes):
    """Move the issue associated with the latest PR to 'canceled' state."""

    if not assert_issue_status(issue, IssueStatus.AWAITING_IMPLEMENTATION, IssueStatus.CANCELED, 'canceled'):
        return

    # not sure why but resolution notes cannot be set anymore during the transition
    if not issue.dry_run(f"update resolution notes on {issue.key}"):
        issue.update(Resolution_Notes=resolution_notes)

    issue.transition_to(IssueTransition.MARK_AS_CANCELED, label=IssueStatus.CANCELED,
                        Resolution=IssueResolution.DECLINED,
                        # Resolution_Notes=resolution_notes,
                        )

    if not issue.dry_run(f"change labels on PR #{pr.number} from {pr.issue_status} to 'Canceled'"):
        pr.remove_label(pr.issue_status)
        pr.add_label(IssueStatus.CANCELED)


def cancel_older_pending_requests(jsm, issue, pr, gh):
    issue.dry_run(f"check for older pending requests to cancel for {issue.key}")
    pulls = list(gh.repo.get_pulls(state='closed', sort='merged_at', direction='desc', base='main')[0:10])
    if pulls:
        old_pr = pulls.pop(0)
        while old_pr.number != pr.number and pulls:  # loop until we find the current PR
            old_pr = pulls.pop(0)
        while pulls:
            if old_pr.number != pr.number:
                old_pr = CustomPullRequest(old_pr)

                if not old_pr.issue_label or pr.issue_prefix not in old_pr.issue_label:
                    old_pr = pulls.pop(0)
                    continue

                if old_pr.issue_status in [IssueStatus.CANCELED, IssueStatus.COMPLETED]:
                    old_pr = pulls.pop(0)
                    continue

                old_issue = None
                try:
                    old_issue = jsm.customer_request(old_pr.issue_label)
                except Exception as e:
                    print(f"It seems that {old_pr.issue_label} is not there anymore")

                print(
                    f"PENDING: PR#{old_pr.number}/{old_pr.issue_label}/{old_pr.issue_status} - {old_issue.key}/{old_issue.status}")

                if old_issue and old_issue.status in [IssueStatus.AWAITING_IMPLEMENTATION, IssueStatus.IMPLEMENTING]:

                    try:
                        move_to_canceled(old_issue, old_pr, f"Superseded by {issue.key}")
                        if issue.dry_run():
                            sleep(10)  # wait for the old_issue to be updated
                    except Exception as e:
                        print(f"Failed to cancel the older pending request {old_issue.key}: {e}")
                        pass

                    if not issue.dry_run(f"cancel the older pending request {old_issue.key}",
                                         f"drop a comment to {issue.key}"):
                        jsm.add_comment(issue.key,
                                        f"{old_issue.key} was automatically canceled due to the completion of this ticket")
                else:
                    old_issue_status = old_issue.status if old_issue else IssueStatus.CANCELED
                    if not issue.dry_run(f"change labels on PR #{old_pr.number} to '{old_issue_status}'"):
                        old_pr.remove_label(old_pr.issue_status)
                        old_pr.add_label(old_issue_status)

            old_pr = pulls.pop(0)
# eof
