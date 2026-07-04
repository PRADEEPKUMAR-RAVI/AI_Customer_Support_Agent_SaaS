"""Import every model so ``Base.metadata`` is fully populated (Alembic + create_all)."""

from app.infra.db.models.conversation import Conversation, Message  # noqa: F401
from app.infra.db.models.knowledge import FileBlob, KbChunk, Source  # noqa: F401
from app.infra.db.models.metrics import TurnMetric  # noqa: F401
from app.infra.db.models.outbox import EmailLog, Outbox, PlatformAuditLog  # noqa: F401
from app.infra.db.models.records import Connector, RecordDataset, RecordRow  # noqa: F401
from app.infra.db.models.tag import TagDef, TicketTag  # noqa: F401
from app.infra.db.models.tenant import (  # noqa: F401
    AgentSettings,
    AllowedDomain,
    Staff,
    Tenant,
    WidgetKey,
)
from app.infra.db.models.ticket import (  # noqa: F401
    InternalNote,
    ResolutionSummary,
    Ticket,
    TicketEvent,
)
