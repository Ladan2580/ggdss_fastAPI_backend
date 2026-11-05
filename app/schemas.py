from typing import Optional, List
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str = Field(min_length=3)
    full_name: str = Field(min_length=1)
    password: str = Field(min_length=6)
    role: str = Field(pattern="^(super_admin|school_admin|teacher)$")


class UserRoleUpdate(BaseModel):
    role: str = Field(pattern="^(super_admin|school_admin|teacher)$")


class StudentCreate(BaseModel):
    full_name: str = Field(min_length=1)
    admission_no: Optional[str] = None
    gender: str = Field(pattern="^(male|female)$")
    date_of_birth: Optional[str] = None
    class_id: str
    arm_id: Optional[str] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    address: Optional[str] = None
    status: str = "active"


class StudentUpdate(StudentCreate):
    pass


class SessionCreate(BaseModel):
    name: str
    term: str
    is_current: bool = False


class ClassCreate(BaseModel):
    name: str
    level: str


class ArmCreate(BaseModel):
    name: str


class SubjectCreate(BaseModel):
    name: str
    code: Optional[str] = None


class AssignmentCreate(BaseModel):
    teacher_id: str
    session_id: str
    class_id: str
    arm_id: Optional[str] = None
    subject_id: str


class ScoreItem(BaseModel):
    student_id: str
    assignment: Optional[int] = Field(default=None, ge=0, le=10)
    first_ca: Optional[int] = Field(default=None, ge=0, le=10)
    second_ca: Optional[int] = Field(default=None, ge=0, le=10)
    exam: Optional[int] = Field(default=None, ge=0, le=70)


class ScoreBatch(BaseModel):
    session_id: str
    class_id: str
    arm_id: Optional[str] = None
    subject_id: str
    items: List[ScoreItem]


class ApprovalAction(BaseModel):
    session_id: str
    class_id: str
    student_id: str
    reason: Optional[str] = None


class AssessmentSettings(BaseModel):
    assignment: int = 10
    first_ca: int = 10
    second_ca: int = 10
    exam: int = 70


class GradeRule(BaseModel):
    grade: str
    min: int
    max: int
    remark: str


class GradingUpdate(BaseModel):
    rules: List[GradeRule]