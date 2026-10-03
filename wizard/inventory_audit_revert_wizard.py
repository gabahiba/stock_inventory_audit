from odoo import fields, models, _


class InventoryAuditRevertWizard(models.TransientModel):
    _name = 'inventory.audit.revert.wizard'
    _description = "Revert Inventory Audit Wizard"

    audit_id = fields.Many2one(
        'inventory.audit', string="Audit", required=True)

    revert_mode = fields.Selection([
        ('keep', "Keep the stock moves (add reverse moves, full history)"),
        ('delete', "Delete the stock moves (as if nothing happened)"),
    ], string="What do you want to do?", default='keep', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.audit_id.action_revert(self.revert_mode)
        return {'type': 'ir.actions.act_window_close'}