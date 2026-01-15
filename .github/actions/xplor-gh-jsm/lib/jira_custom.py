import json
from typing import Any
from urllib.parse import urlparse

from jira import Issue, JIRA
from jira.resilientsession import ResilientSession
from jira.resources import Resource

from .gh_enums import IssueStatus, IssueResolution, as_list
from .utils import compact_str, compact_list_contains


class RequestTypeFields(Resource):
    def __init__(
            self,
            options: dict[str, str],
            session: ResilientSession,
            service_desk_id: str | int,
            request_type_id: str | int,
    ):
        Resource.__init__(
            self,
            "servicedesk/{0}/requesttype/{1}/field",
            options,
            session,
            "{server}/rest/servicedeskapi/{path}",
        )
        self.find((service_desk_id, request_type_id))
        self.fields = set([v.__dict__["fieldId"] for v in self.requestTypeFields])


class CustomerRequest(Issue):
    def __init__(self, issue, jira):
        super().__init__(issue._options, issue._session, issue.raw)
        self.__dict__.update(issue.__dict__)
        self.debug_print = jira.debug_print
        self.dry_run = jira.dry_run
        self.required_fields_to_clone = jira.required_fields_to_clone
        self.request_type_id = jira.request_type_id
        self.service_desk_id = jira.service_desk_id
        self.named_fields = jira.field_name_to_id
        #
        self._jira_transitions = jira.transitions
        self._jira_transition_issue = jira.transition_issue

        #
        parsed_url = urlparse(self.self)
        self.browser_url = f"{parsed_url.scheme}://{parsed_url.netloc}/browse/{self.key}"

        #
        try:
            self.status = IssueStatus(self.fields.status.name)
        except ValueError:
            self.status = IssueStatus.UNKNOWN

    def update(  # type: ignore[override] # incompatible supertype ignored
            self,
            fields: dict[str, Any] = None,
            update: dict[str, Any] = None,
            async_: bool = None,
            jira: JIRA = None,
            notify: bool = True,
            append: bool = False,
            **fieldargs,
    ):
        if fieldargs:
            fields = fields or {}
            for field_name in fieldargs.keys():
                key = compact_str(field_name)
                if key in self.named_fields:
                    key = self.named_fields[key]
                    value = fieldargs[field_name]
                    if append and isinstance(value, str):
                        value = f"{self.fields.__dict__.get(key)}\n{value}"
                    fields[key] = value
                    continue
                raise Exception(f"Field '{field_name}' not found in request {self.key}.")
            fieldargs = {}

        super().update(fields, update, async_, jira, notify, **fieldargs)

    def get_next_forward_transition(self, transition_name_list):
        transition_name_list = as_list(transition_name_list)
        transitions = self._jira_transitions(self.key, expand="transitions.fields")
        self.debug_print(f"Available transitions for issue {self.key}: {[t['name'] for t in transitions]}")
        for transition in transitions:
            self.debug_print(transition)
            if compact_list_contains(transition_name_list, transition['name']):
                return transition
        return None

    def transition_to(self, transition_name_list, label, fields_dict=None, **form_fields):
        transition_name_list = as_list(transition_name_list)
        label = label.value if isinstance(label, IssueStatus) else label
        fields_dict = fields_dict or {}

        while True:
            transition = self.get_next_forward_transition(transition_name_list)
            if not transition:
                break

            # add form fields if any
            if form_fields:
                if not 'fields' in transition:
                    raise Exception(f"No fields found in transition for issue {self.key} to '{label}' status.")
                self.debug_print(f"Transition fields for issue {self.key} to '{transition['name']}' state:")
                self.debug_print(json.dumps(transition['fields'], indent=4))
                for k, v in form_fields.items():
                    form_field = compact_str(k)
                    for f in transition['fields'].values():
                        field_key = compact_str(f.get('key'))
                        field_name = compact_str(f.get('name'))
                        if form_field == field_name:
                            # edge case
                            if field_name == 'resolution':
                                v = v.value if isinstance(v, IssueResolution) else v
                                v = compact_str(v)
                                resolution = next((x for x in f['allowedValues'] if compact_str(x['name']) == v), None)
                                if not resolution:
                                    print(json.dumps(transition, indent=4))
                                    raise Exception(
                                        f"No '{v}' resolution found in allowed values for issue {self.key} to {transition['name']}.")
                                fields_dict[field_key] = {"id": resolution["id"]}
                            else:
                                fields_dict[field_key] = v

            self.debug_print(json.dumps(fields_dict, indent=4))

            #
            if self.dry_run(f"move issue {self.key} to '{label}' state"):
                return

            self._jira_transition_issue(self.key, transition["id"], fields=fields_dict)
            self.update()
