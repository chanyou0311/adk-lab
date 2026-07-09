"""mock ツール (data warehouse = DuckDB, slack/billing/oncall/portal = JSON fixture)。

- bq / slack      : gold ツール (CLEAN 環境)
- billing / oncall: 別ドメイン (DISTINCT 環境で「数」を足す)
- portal          : near-synonym distractor (CONFUSABLE 環境で「紛らわしさ」を足す)
"""

from .billing_tools import make_billing_tools
from .bq_tools import make_bq_tools
from .oncall_tools import make_oncall_tools
from .portal_tools import make_portal_tools
from .slack_tools import make_slack_tools

__all__ = [
    "make_billing_tools",
    "make_bq_tools",
    "make_oncall_tools",
    "make_portal_tools",
    "make_slack_tools",
]
