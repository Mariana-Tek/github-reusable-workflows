from enum import Enum


class InsensitiveEnum(Enum):
    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            # Normalize the input string to match enum values case-insensitively
            for member in cls:
                if member.value.lower() == value.lower():
                    return member
        # If no match is found, raise a ValueError (default behavior)
        raise ValueError(f"{value!r} is not a valid {cls.__name__}")


class IssueResolution(InsensitiveEnum):
    DONE = 'Done'
    DECLINED = 'Declined'
    # WONT_DO = "Won't Do" # it's not a valid resolution in JSM anymore
    DUPLICATE = 'Duplicate'
    SUCCESSFUL = 'Successful'
    SUCCESSFUL_WITH_ISSUES = 'Successful with Issues'
    PARTIALLY_SUCCESSFUL = 'Partially Successful'
    FAILED = 'Failed'
    CANNOT_REPRODUCE = 'Cannot Reproduce'


class IssueStatus(InsensitiveEnum):
    UNKNOWN = 'Unknown'
    AWAITING_IMPLEMENTATION = 'Awaiting Implementation'
    IMPLEMENTING = 'Implementing'
    COMPLETED = 'Completed'
    CANCELED = 'Canceled'


class IssueTransition(InsensitiveEnum):
    NORMAL_CHANGE = 'Normal Change'
    STANDARD_CHANGE = 'Standard Change'
    IMPLEMENT = 'Implement'
    COMPLETE = 'Complete'
    MARK_AS_CANCELED = 'Mark as Canceled'


def as_list(value):
    value = value if isinstance(value, list) else [value]
    value = [s.value if isinstance(s, IssueStatus) or isinstance(s, IssueTransition) else s for s in value]
    return value
