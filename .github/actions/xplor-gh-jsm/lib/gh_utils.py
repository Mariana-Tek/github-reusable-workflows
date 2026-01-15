import os
import re

from github import Github
from github.PullRequest import PullRequest

from .gh_enums import IssueStatus


def gh_output_env_vars(**kwargs):
    """
    Safely outputs environment variables to the GitHub Actions output.
    :param kwargs: Key-value pairs to output as environment variables.
    """
    if os.environ.get('GITHUB_OUTPUT') is not None:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output_file:
            for name, value in kwargs.items():
                output_file.write(f'{name}={value}\n')


class CustomPullRequest(PullRequest):
    """
    ITSM Pull Request class that extends the GitHub PullRequest class.
    This class retrieves the issue label from the pull request and provides methods to label the PR.
    """
    issue_label = None
    issue_status = IssueStatus.UNKNOWN

    def __init__(self, pr):
        self.__dict__.update(pr.__dict__)
        self.retrieve_issue_label()

    def get_approvers(self):
        reviews = self.get_reviews()
        reviews = [review for review in reviews if review.user.login != 'github-actions[bot]']
        reviews.sort(key=lambda x: x.submitted_at, reverse=True)
        approved_reviews = [review for review in reviews if review.state == 'APPROVED']
        return [review.user.login for review in approved_reviews]

    def add_label(self, label):
        label = label.value if isinstance(label, IssueStatus) else label
        if not label:
            raise ValueError("Label cannot be empty")
        labels = [label.name for label in self.get_labels()]
        if label not in labels:
            self.add_to_labels(label)

    def remove_label(self, label):
        label = label.value if isinstance(label, IssueStatus) else label
        if not label:
            raise ValueError("Label cannot be empty")
        labels = [label.name for label in self.get_labels()]
        if label in labels:
            self.remove_from_labels(label)

    def retrieve_issue_label(self):
        labels = [label.name for label in self.get_labels()]
        self.issue_label = next((label for label in labels if label.startswith('ITSM-')), None)
        if not self.issue_label:
            self.issue_label = next((label for label in labels if label.startswith('ITPOC-')), None)
        self.issue_prefix = self.issue_label.split('-')[0] if self.issue_label else None
        # states
        for label in labels:
            try:
                self.issue_status = IssueStatus(label)
            except ValueError:
                continue
        return self.issue_label


class ReleasePR:
    """
    A minimal PR-like object for releases that don't have an associated PR.
    This allows the JSM workflow to work with releases.
    """
    def __init__(self, release_tag=None, release_url=None, actor_login=None):
        self.number = None  # No PR number for releases
        self.html_url = release_url or os.getenv('GITHUB_SERVER_URL', '') + '/' + os.getenv('GITHUB_REPOSITORY', '') + '/releases'
        self.user = type('obj', (object,), {'login': actor_login or os.getenv('GITHUB_ACTOR', 'unknown')})()
        self.title = f"Release {release_tag or os.getenv('GITHUB_REF_NAME', 'unknown')}"
        self.body = f"Release deployment for {release_tag or os.getenv('GITHUB_REF_NAME', 'unknown')}"
        self.issue_label = None
        self.issue_status = None
        
    def get_approvers(self):
        """Releases don't have approvers"""
        return []
    
    def add_label(self, label):
        """Releases can't be labeled - this is a no-op"""
        print(f"Note: Cannot add label '{label}' to release (no PR to label)")
        pass
    
    def remove_label(self, label):
        """Releases can't have labels removed - this is a no-op"""
        pass
    
    def create_issue_comment(self, comment):
        """Releases can't have comments - this is a no-op"""
        print(f"Note: Cannot comment on release: {comment}")
        pass


class GHUtils:
    issue_label = None

    def __init__(self, debug=False):
        github_token = os.getenv('GITHUB_TOKEN')
        if not github_token:
            raise Exception("GITHUB_TOKEN not found in environment variables")
        repo_name = os.getenv('GITHUB_REPOSITORY')
        if not repo_name:
            raise Exception("GITHUB_REPOSITORY not found in environment variables")
        self.g = Github(github_token)
        self.repo = self.g.get_repo(repo_name)
        if not self.repo:
            raise Exception(f"Repository {repo_name} not found or failed to retrieve")
        self._debug = debug

    def get_pr(self, pr_number, skip_label_validation=False):

        # Validate and convert PR number to integer when necessary
        if f"{pr_number}".startswith("PR-"):
            pr_str = re.match(r'PR-(\d+)', pr_number)
            if pr_str:
                pr_number = int(pr_str.group(1))

        pr = CustomPullRequest(self.repo.get_pull(pr_number))
        if not pr:
            raise Exception(f"Pull request #{pr_number} not found")

        if skip_label_validation:
            if self._debug:
                print(f"Skipping label validation for PR #{pr_number}")
            return pr

        if not pr.issue_label:
            raise Exception(f"Pull request #{pr_number} does not have an ITSM- or ITPOC- label")

        return pr
    
    def get_release_pr(self, release_tag=None):
        """Get a ReleasePR object for releases that don't have an associated PR"""
        release_url = None
        if release_tag:
            try:
                release = self.repo.get_release(release_tag)
                release_url = release.html_url
            except Exception as e:
                if self._debug:
                    print(f"Could not get release {release_tag}: {e}")
        
        return ReleasePR(release_tag=release_tag, release_url=release_url)
