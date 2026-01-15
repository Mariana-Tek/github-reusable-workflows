import json
import re
from io import BytesIO

from jira import JIRA, Issue, JIRAError
from jira.resilientsession import PrepareRequestForRetry
from requests.structures import CaseInsensitiveDict
from requests_toolbelt import MultipartEncoder

from .jira_custom import CustomerRequest, RequestTypeFields
from .utils import compact_str


class JiraITSM(JIRA):
    _project_name = "ITSM"
    _request_type = "Request a change"

    def __init__(self, server, username, password, debug=False, dry_run=False, **kwargs):
        super().__init__(server=server, basic_auth=(username, password), **kwargs)
        self._debug = debug
        self._dry_run = dry_run

        # fields
        fields = self._get_json("field")
        self.field_name_to_id = {compact_str(v['untranslatedName'] if 'untranslatedName' in v else v['name']): v["id"]
                                 for v in fields}
        self.field_id_to_name = {v: k for k, v in self.field_name_to_id.items()}
        # add also the compacted-id to id mapping
        self.field_name_to_id = {**{compact_str(v['id']): v['id'] for v in fields}, **self.field_name_to_id}

        service_desks = self.service_desks()
        service_desk = next((sd for sd in service_desks if self._project_name in sd.projectName), None)
        if not service_desk:
            raise ValueError(f"Service Desk with project name '{self._project_name}' not found.")
        request_types = self.request_types(service_desk.id)
        request_type = next((rt for rt in request_types if rt.name == self._request_type), None)
        if not request_type:
            raise ValueError(
                f"Request Type '{self._request_type}' not found in Service Desk '{service_desk.projectName}'.")

        self.service_desk_id = service_desk.id
        self.project_key = service_desk.projectKey
        self.request_type_id = request_type.id

        # required fields to clone
        request_type_fields = RequestTypeFields(self._options, self._session, service_desk.id, request_type.id)
        valid_field_id_set = set(request_type_fields.fields)
        # workaround for PROD jira, since some fields were set as "hidden" in the portal, but are actually required
        for field in ['requesttype', 'changetype', 'team', 'affectedservicesportal']:
            if field in self.field_name_to_id:
                valid_field_id_set.add(self.field_name_to_id[field])
        valid_field_id_list = [compact_str(x) for x in valid_field_id_set]
        self.required_fields_to_clone = {k: v for k, v in self.field_name_to_id.items() if k in valid_field_id_list}

    def debug_print(self, msg):
        if self._debug:
            print(f"DEBUG: {msg}")

    def dry_run(self, *warn_msgs: str):
        if self._dry_run and warn_msgs:
            print('\n'.join(f'DRY RUN: Would {line}' for line in warn_msgs))
        return self._dry_run

    def customer_request(self, request_id_or_key: str | Issue):
        """
        Get an issue by its ID or key.
        :param request_id_or_key: Issue ID or key.
        :return: CustomerRequest object.
        """
        issue = super().issue(request_id_or_key)
        return CustomerRequest(issue, jira=self)

    def clone_request(self, template_key, summary, header='', description=None, reporter=None, assignee=None):
        """
        Clone a customer request based on a template issue.
        :param template_key: The key of the template issue to clone.
        :param summary: The summary for the new request.
        :param header: Optional header to include in the description.
        :param description: The description for the new request. If None, uses the template's description.
        :param reporter: The reporter accountId for the new request. If None, assigns to the current user.
        :param assignee: The assignee accountId for the new request. If None, assigns to the current user.
        :return: A new CustomerRequest object.
        """

        def parse_value(value):
            if value is None:
                return None
            if hasattr(value, "raw"):
                value = value.raw
            #
            if hasattr(value, "value"):
                return parse_value(value.value)
            if hasattr(value, "id"):
                if isinstance(value.id, str) and re.match(
                        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", value.id):
                    return value.id
                return {"id": value.id}
            if hasattr(value, "requestType"):
                return value.requestType.id
            if isinstance(value, list):
                if len(value) == 0:
                    return None
                return [parse_value(v) for v in value]
            if isinstance(value, dict) and "id" in value:
                return {"id": value["id"]}
            if re.match(r'^\d{4}-\d{2}-\d{2}T', value):
                return None  # skip date fields
            return value

        template = self.customer_request(template_key)
        self.debug_print(json.dumps(template.raw))

        if description is None:
            description = template.fields.description or ""

        payload = {
            "project": {"key": template.fields.project.key},
            "issuetype": {"id": template.fields.issuetype.id},
            "summary": summary,
            "description": f"{header}\n{description}",
        }
        if reporter:
            payload["reporter"] = {"accountId": reporter}

        for field_id in template.required_fields_to_clone.values():
            if field_id in payload:
                continue
            if field_id in template.fields.__dict__:
                value = getattr(template.fields, field_id)
                value = parse_value(value)
                if value is None:
                    continue
                payload[field_id] = value

        if self._debug or self.dry_run("create a new request with the following payload:"):
            self.debug_print(json.dumps(payload, indent=4))
            self.debug_print("\n\nThe following fields will be set:")
            for key in sorted(payload.keys()):
                name = self.field_id_to_name.get(key, key)
                print(f" - {name} ({key}) = {json.dumps(payload[key])}")
            print("\n\n")

        assignee = assignee or self.current_user()
        if self.dry_run(f"assign the new request to {assignee} (me={self.current_user()})."):
            return None

        new_issue = self.create_issue(fields=payload)

        print(new_issue.key)

        # link the cloned request to the original one
        self.create_issue_link(
            type="Cloners",
            outwardIssue=template.key,
            inwardIssue=new_issue.key
        )

        # assign it to the assignee
        # for some reason the standard assign_issue does not work here
        # self.assign_issue(new_issue.key, assignee=-1)
        url = self._get_latest_url(f"issue/{new_issue.key}/assignee")
        try:
            self._session.put(url, data=json.dumps({"accountId": assignee}))
        except JIRAError as e:
            print(f"WARNING: Failed to assign issue {new_issue.key} to {assignee}: {e}")
            print(f"         Assigning to the current user {self.current_user()} instead.")
            self._session.put(url, data=json.dumps({"accountId": self.current_user()}))

        return CustomerRequest(new_issue, self)

    def add_temporary_attachment(self, file_content, content_type: str, filename: str):
        attachment_io = BytesIO(file_content)

        def generate_multipartencoded_request_args() -> tuple[
            MultipartEncoder, CaseInsensitiveDict
        ]:
            """Returns MultipartEncoder stream of attachment, and the header."""
            attachment_io.seek(0)
            encoded_data = MultipartEncoder(
                fields={"file": (filename, attachment_io, content_type)}
            )
            request_headers = CaseInsensitiveDict(
                {
                    "content-type": encoded_data.content_type,
                    "X-Atlassian-Token": "no-check",
                }
            )
            return encoded_data, request_headers

        class RetryableMultipartEncoder(PrepareRequestForRetry):
            def prepare(
                    self, original_request_kwargs: CaseInsensitiveDict
            ) -> CaseInsensitiveDict:
                encoded_data, request_headers = generate_multipartencoded_request_args()
                original_request_kwargs["data"] = encoded_data
                original_request_kwargs["headers"] = request_headers
                return super().prepare(original_request_kwargs)

        url = f"{self.server_url}/rest/servicedeskapi/servicedesk/{self.service_desk_id}/attachTemporaryFile"
        encoded_data, request_headers = generate_multipartencoded_request_args()
        response = self._session.post(
            url,
            data=encoded_data,
            headers=request_headers,
            _prepare_retry_class=RetryableMultipartEncoder(),  # type: ignore[call-arg] # ResilientSession handles
        )
        response.raise_for_status()
        ret = response.json()
        self.debug_print(f"Added temporary attachment '{ret['temporaryAttachments'][0]}'")
        return ret['temporaryAttachments'][0]
