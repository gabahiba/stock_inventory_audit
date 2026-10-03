# Outils Odoo : api (décorateurs), Command (créer des lignes liées),
# fields (champs), models (classe de base), _ (traduction)
from odoo import api, Command, fields, models, _

# UserError : message d'erreur propre affiché à l'utilisateur
from odoo.exceptions import UserError

# float_is_zero : compare un nombre décimal à zéro sans erreur d'arrondi
from odoo.tools import float_is_zero

# expression : permet de combiner plusieurs domaines avec OR / AND
from odoo.osv import expression


class InventoryAudit(models.Model):
    _name = 'inventory.audit'
    _description = "Inventory Audit"
    _order = 'audit_date desc, id desc'

    # ------------------------------------------------------------------
    # Champs de l'en-tête
    # ------------------------------------------------------------------

    name = fields.Char(
        string="Reference", required=True, copy=False,
        default=lambda self: _("New Inventory Audit"))

    audit_date = fields.Datetime(
        string="Audit Date", required=True, default=fields.Datetime.now)

    user_id = fields.Many2one(
        'res.users', string="Responsible",
        default=lambda self: self.env.user)

    company_id = fields.Many2one(
        'res.company', string="Company", required=True,
        default=lambda self: self.env.company)

    # "reverted" et "cancelled" sont des états finaux
    state = fields.Selection([
        ('draft', "Draft"),
        ('in_progress', "In Progress"),
        ('validated', "Validated"),
        ('reverted', "Reverted"),
        ('cancelled', "Cancelled"),
    ], string="Status", default='draft', required=True, copy=False)

    # ------------------------------------------------------------------
    # Périmètre à cases à cocher (un ou plusieurs à la fois)
    # ------------------------------------------------------------------

    scope_warehouse = fields.Boolean(string="Warehouse", default=True)
    scope_category = fields.Boolean(string="Product Category")
    scope_product = fields.Boolean(string="Specific Products")
    scope_location = fields.Boolean(string="Specific Locations")

    warehouse_id = fields.Many2one('stock.warehouse', string="Warehouse")
    category_ids = fields.Many2many(
        'product.category', string="Product Categories")
    product_ids = fields.Many2many('product.product', string="Specific Products")
    location_ids = fields.Many2many(
        'stock.location', string="Specific Locations",
        domain=[('usage', '=', 'internal')])

    scope_summary = fields.Char(
        string="Audit Scope", compute='_compute_scope_summary', store=True)

    @api.depends('scope_warehouse', 'scope_category',
                 'scope_product', 'scope_location')
    def _compute_scope_summary(self):
        labels = {
            'scope_warehouse': _("Warehouse"),
            'scope_category': _("Product Category"),
            'scope_product': _("Specific Products"),
            'scope_location': _("Specific Locations"),
        }
        for audit in self:
            selected = [labels[f] for f in labels if audit[f]]
            audit.scope_summary = ", ".join(selected) or _("None")

    # ------------------------------------------------------------------
    # Autres champs
    # ------------------------------------------------------------------

    line_ids = fields.One2many(
        'inventory.audit.line', 'audit_id', string="Audit Lines")

    move_ids = fields.One2many(
        'stock.move', 'inventory_audit_id', string="Stock Moves")

    move_count = fields.Integer(
        string="Moves Count", compute='_compute_move_count')

    # ------------------------------------------------------------------
    # Référence unique (numérotation automatique)
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _("New Inventory Audit"):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('inventory.audit')
                    or _("New Inventory Audit"))
        return super().create(vals_list)

    @api.constrains('name', 'company_id')
    def _check_name_unique(self):
        for audit in self:
            duplicates = self.search_count([
                ('name', '=', audit.name),
                ('company_id', '=', audit.company_id.id),
                ('id', '!=', audit.id),
            ])
            if duplicates:
                raise UserError(_(
                    "The reference must be unique: '%s' already exists.",
                    audit.name))

    # ------------------------------------------------------------------
    # Bouton "Start Inventory"
    # ------------------------------------------------------------------

    def _get_quant_domain(self):
        self.ensure_one()

        base_domain = [
            ('location_id.usage', '=', 'internal'),
            ('company_id', '=', self.company_id.id),
            ('quantity', '!=', 0),
        ]

        scope_domains = []

        if self.scope_warehouse:
            if not self.warehouse_id:
                raise UserError(_("Please select a warehouse."))
            scope_domains.append([(
                'location_id', 'child_of',
                self.warehouse_id.view_location_id.id)])

        if self.scope_category:
            if not self.category_ids:
                raise UserError(_("Please select at least one product category."))
            scope_domains.append([(
                'product_id.categ_id', 'child_of', self.category_ids.ids)])

        if self.scope_product:
            if not self.product_ids:
                raise UserError(_("Please select at least one product."))
            scope_domains.append([('product_id', 'in', self.product_ids.ids)])

        if self.scope_location:
            if not self.location_ids:
                raise UserError(_("Please select at least one location."))
            scope_domains.append([(
                'location_id', 'child_of', self.location_ids.ids)])

        if not scope_domains:
            raise UserError(_("Please select at least one audit scope."))

        return expression.AND([base_domain, expression.OR(scope_domains)])

    def action_start(self):
        for audit in self:
            if audit.state != 'draft':
                raise UserError(_("Only a draft audit can be started."))

            quants = self.env['stock.quant'].search(audit._get_quant_domain())
            if not quants:
                raise UserError(_("No stock found for the selected scope."))

            audit.line_ids.unlink()

            vals_list = []
            for quant in quants:
                vals_list.append({
                    'audit_id': audit.id,
                    'product_id': quant.product_id.id,
                    'location_id': quant.location_id.id,
                    'lot_id': quant.lot_id.id,
                    'theoretical_qty': quant.quantity,
                    'counted_qty': quant.quantity,
                })

            self.env['inventory.audit.line'].create(vals_list)
            audit.state = 'in_progress'

    # ------------------------------------------------------------------
    # Bouton "Validate Inventory"
    # ------------------------------------------------------------------

    def _create_stock_move(self, line):
        self.ensure_one()

        inventory_loss = line.product_id.with_company(
            self.company_id).property_stock_inventory

        qty = abs(line.difference_qty)

        if line.difference_qty > 0:
            source, dest = inventory_loss, line.location_id
        else:
            source, dest = line.location_id, inventory_loss

        move_vals = {
            'product_id': line.product_id.id,
            'product_uom': line.product_id.uom_id.id,
            'product_uom_qty': qty,
            'location_id': source.id,
            'location_dest_id': dest.id,
            'company_id': self.company_id.id,
            'origin': self.name,
            'inventory_audit_id': self.id,
            'is_inventory': True,
            'picked': True,
            'move_line_ids': [Command.create({
                'product_id': line.product_id.id,
                'product_uom_id': line.product_id.uom_id.id,
                'quantity': qty,
                'lot_id': line.lot_id.id,
                'location_id': source.id,
                'location_dest_id': dest.id,
                'company_id': self.company_id.id,
            })],
        }

        if 'name' in self.env['stock.move']._fields:
            move_vals['name'] = _("Inventory Audit: %s", self.name)

        move = self.env['stock.move'].create(move_vals)
        move._action_done()

        move.write({'date': self.audit_date})
        move.move_line_ids.write({'date': self.audit_date})

    def action_validate(self):
        for audit in self:
            if audit.state != 'in_progress':
                raise UserError(_("Only an audit in progress can be validated."))

            for line in audit.line_ids:
                rounding = line.product_id.uom_id.rounding
                if float_is_zero(line.difference_qty, precision_rounding=rounding):
                    continue

                if line.product_id.tracking != 'none' and not line.lot_id:
                    raise UserError(_(
                        "Please set a Lot/Serial Number on the line of %s.",
                        line.product_id.display_name))

                audit._create_stock_move(line)

            audit.state = 'validated'

    # ------------------------------------------------------------------
    # Bouton "Cancel Inventory"
    # ------------------------------------------------------------------

    def action_cancel(self):
        for audit in self:
            # Un audit validé ou reverted ne peut plus être annulé
            if audit.state in ('validated', 'reverted'):
                raise UserError(_(
                    "A validated or reverted audit cannot be cancelled."))
            audit.state = 'cancelled'

    # ------------------------------------------------------------------
    # Bouton "Revert" -> ouvre le wizard de choix Keep / Delete
    # ------------------------------------------------------------------

    def action_open_revert_wizard(self):
        self.ensure_one()
        if self.state != 'validated':
            raise UserError(_("Only a validated audit can be reverted."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Revert Audit"),
            'res_model': 'inventory.audit.revert.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_audit_id': self.id},
        }

    def _revert_keep_moves(self):
        # KEEP : garde les mouvements d'origine et crée un mouvement inverse
        # pour chacun. Les inverses sont liés au même audit
        # (inventory_audit_id), donc le smart button "Stock Moves"
        # affiche tous les mouvements (originaux + inverses).
        self.ensure_one()

        # Liste figée AVANT la boucle : les mouvements inverses créés
        # ci-dessous n'en font pas partie, donc pas de double inversion
        done_moves = self.move_ids.filtered(lambda m: m.state == 'done')

        for move in done_moves:
            lot = move.move_line_ids[:1].lot_id

            reverse_vals = {
                'product_id': move.product_id.id,
                'product_uom': move.product_uom.id,
                'product_uom_qty': move.product_uom_qty,
                # Échange : l'ancienne destination devient la nouvelle source
                'location_id': move.location_dest_id.id,
                'location_dest_id': move.location_id.id,
                'company_id': move.company_id.id,
                'origin': _("Revert: %s", self.name),
                'inventory_audit_id': self.id,
                'is_inventory': True,
                'picked': True,
                'move_line_ids': [Command.create({
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'quantity': move.product_uom_qty,
                    'lot_id': lot.id,
                    'location_id': move.location_dest_id.id,
                    'location_dest_id': move.location_id.id,
                    'company_id': move.company_id.id,
                })],
            }

            if 'name' in self.env['stock.move']._fields:
                reverse_vals['name'] = _("Revert: %s", self.name)

            reverse_move = self.env['stock.move'].create(reverse_vals)
            # Valide immédiatement : remet le stock à son état d'avant
            reverse_move._action_done()

    def _revert_delete_moves(self):
        # DELETE : remet les quantités comme avant l'audit ET supprime
        # tous les mouvements, comme si rien n'avait été fait
        self.ensure_one()
        moves = self.move_ids.sudo().filtered(lambda m: m.state == 'done')
        Quant = self.env['stock.quant'].sudo()

        # 1) Annuler l'effet sur le stock (quants), ligne par ligne
        for line in moves.move_line_ids:
            qty = line.quantity_product_uom
            Quant._update_available_quantity(
                line.product_id, line.location_dest_id, -qty,
                lot_id=line.lot_id)
            Quant._update_available_quantity(
                line.product_id, line.location_id, qty,
                lot_id=line.lot_id)

        # 2) Supprimer les valorisations liées (si compta stock installée)
        if 'stock.valuation.layer' in self.env:
            self.env['stock.valuation.layer'].sudo().search(
                [('stock_move_id', 'in', moves.ids)]).unlink()

        # 3) Supprimer les mouvements (repassés en brouillon avant)
        move_lines = moves.move_line_ids
        moves.write({'state': 'draft'})
        move_lines.unlink()
        moves.unlink()

    def action_revert(self, mode):
        # Appelée par le wizard après confirmation
        # mode = 'keep'   -> mouvements gardés + mouvements inverses créés
        # mode = 'delete' -> stock restauré + tous les mouvements supprimés
        self.ensure_one()
        if self.state != 'validated':
            raise UserError(_("Only a validated audit can be reverted."))

        if mode == 'delete':
            self._revert_delete_moves()
        else:
            self._revert_keep_moves()

        # Dans les DEUX cas : statut final "Reverted"
        self.state = 'reverted'

    # ------------------------------------------------------------------
    # Smart button "Stock Moves"
    # ------------------------------------------------------------------

    @api.depends('move_ids')
    def _compute_move_count(self):
        for audit in self:
            audit.move_count = len(audit.move_ids)

    def action_view_moves(self):
        self.ensure_one()
        list_view = self.env.ref('stock_inventory_audit.inventory_audit_move_view_list')
        return {
            'type': 'ir.actions.act_window',
            'name': _("Stock Moves"),
            'res_model': 'stock.move',
            'views': [(list_view.id, 'list'), (False, 'form')],
            'domain': [('inventory_audit_id', '=', self.id)],
        }