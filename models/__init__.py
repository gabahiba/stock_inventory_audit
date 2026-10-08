# Le mixin doit être chargé AVANT inventory_audit (qui en hérite)
from . import inventory_historical_mixin
from . import inventory_audit
from . import inventory_audit_line
from . import stock_move
from . import inventory_historical_qty_wizard