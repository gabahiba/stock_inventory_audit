from odoo import api, fields, models, _

from odoo.exceptions import UserError


class InventoryAuditLine(models.Model):
    _name = 'inventory.audit.line'
    _description = "Inventory Audit Line"

    # Audit parent (cascade : supprimer l'audit supprime ses lignes)
    audit_id = fields.Many2one(
        'inventory.audit', string="Audit", required=True, ondelete='cascade')

    # Statut lu depuis l'audit
    state = fields.Selection(related='audit_id.state', string="Status")

    # Produit audité
    product_id = fields.Many2one(
        'product.product', string="Product", required=True)

    # Emplacement audité
    location_id = fields.Many2one(
        'stock.location', string="Location", required=True)

    # Lot/série (uniquement ceux du produit de la ligne)
    lot_id = fields.Many2one(
        'stock.lot', string="Lot/Serial Number",
        domain="[('product_id', '=', product_id)]")

    # Stock du système : calculé à la date du comptage au démarrage,
    # puis mis à jour par le bouton "Refresh" avec les opérations
    # faites depuis (écrit par le code, jamais à la main)
    theoretical_qty = fields.Float(
        string="Theoretical Quantity", readonly=True, digits='Product Unit')

    # Saisi par le personnel d'entrepôt (décalé par "Refresh" de la
    # même variation que la théorique)
    counted_qty = fields.Float(
        string="Counted Quantity", default=0.0, digits='Product Unit')

    # Écart = comptée - théorique (inchangé par "Refresh")
    difference_qty = fields.Float(
        string="Difference", compute='_compute_difference_qty',
        store=True, digits='Product Unit')

    @api.depends('counted_qty', 'theoretical_qty')
    def _compute_difference_qty(self):
        for line in self:
            # + = gain, - = perte
            line.difference_qty = line.counted_qty - line.theoretical_qty

    def _check_audit_editable(self):
        # Bloque si l'audit est Validated ou Cancelled
        for line in self:
            if line.audit_id.state in ('validated', 'cancelled'):
                raise UserError(_(
                    "You cannot add or modify lines of a validated "
                    "or cancelled audit."))

    @api.model_create_multi
    def create(self, vals_list):
        # Lignes pas encore créées : contrôle sur les données à créer
        for vals in vals_list:
            audit = self.env['inventory.audit'].browse(vals.get('audit_id'))
            if audit.state in ('validated', 'cancelled'):
                raise UserError(_(
                    "You cannot add or modify lines of a validated "
                    "or cancelled audit."))
        return super().create(vals_list)

    def write(self, vals):
        self._check_audit_editable()
        return super().write(vals)

    def unlink(self):
        self._check_audit_editable()
        return super().unlink()