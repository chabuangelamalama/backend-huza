from models.business import ApprovalStatus
from models.location import OsmType


def test_enum_values_print_without_the_class_name():
    assert str(ApprovalStatus.PENDING) == "PENDING"
    assert f"{OsmType.NODE}" == "NODE"
