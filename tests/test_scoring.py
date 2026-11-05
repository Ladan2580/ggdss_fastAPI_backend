from app.helpers import grade_for, competition_rank


RULES = [
    {"grade": "A", "min": 70, "max": 100, "remark": "Excellent"},
    {"grade": "B", "min": 60, "max": 69, "remark": "Very Good"},
    {"grade": "C", "min": 50, "max": 59, "remark": "Good"},
    {"grade": "D", "min": 45, "max": 49, "remark": "Credit"},
    {"grade": "E", "min": 40, "max": 44, "remark": "Pass"},
    {"grade": "F", "min": 0, "max": 39, "remark": "Fail"},
]


def test_grade_boundaries():
    assert grade_for(100, RULES) == ("A", "Excellent")
    assert grade_for(70, RULES) == ("A", "Excellent")
    assert grade_for(69, RULES) == ("B", "Very Good")
    assert grade_for(59, RULES) == ("C", "Good")
    assert grade_for(49, RULES) == ("D", "Credit")
    assert grade_for(44, RULES) == ("E", "Pass")
    assert grade_for(39, RULES) == ("F", "Fail")


def test_competition_ranking_with_ties():
    assert competition_rank([90, 80, 80, 70]) == [1, 2, 2, 4]
    assert competition_rank([100, 90, 90, 90, 80]) == [1, 2, 2, 2, 5]