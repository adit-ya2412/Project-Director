"""Import every model so Base.metadata is complete for Alembic autogenerate.
Nothing here should be imported by application code directly - repositories
import the specific model modules they need."""

from app.models.asset import AssetModel
from app.models.domain_event import DomainEventModel
from app.models.generated_clip import GeneratedClipModel
from app.models.llm_call import LlmCallModel
from app.models.narration import NarrationModel
from app.models.project import ProjectModel
from app.models.render import RenderModel
from app.models.script import ScriptModel
from app.models.shot_binding import ShotBindingModel
from app.models.timeline_version import TimelineVersionModel
from app.models.workflow import WorkflowRunModel, WorkflowStepAttemptModel

__all__ = [
    "AssetModel",
    "DomainEventModel",
    "GeneratedClipModel",
    "LlmCallModel",
    "NarrationModel",
    "ProjectModel",
    "RenderModel",
    "ScriptModel",
    "ShotBindingModel",
    "TimelineVersionModel",
    "WorkflowRunModel",
    "WorkflowStepAttemptModel",
]
