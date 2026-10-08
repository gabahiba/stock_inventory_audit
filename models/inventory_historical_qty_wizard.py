from datetime import datetime, time, timedelta

import pytz

from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class InventoryHistoricalQtyWizard(models.TransientModel):
    _name = 'inventory.historical.qty.wizard'
    # On récupère _get_period_report du mixin
    _inherit = ['inventory.historical.mixin']
    _description = "Historical Quantity Wizard"

    date = fields.Datetime(
        string="Date", required=True, default=fields.Datetime.now,
        help="Date and time used by 'Quantity at Date'. "
             "'Moves of the Day' uses the whole day of this date.")

    company_id = fields.Many2one(
        'res.company', string="Company", required=True,
        default=lambda self: self.env.company)

    # Filtres OPTIONNELS (combinés avec ET). Si on n'en choisit aucun,
    # tous les produits et tous les emplacements sont inclus.
    warehouse_id = fields.Many2one('stock.warehouse', string="Warehouse")
    location_ids = fields.Many2many(
        'stock.location', string="Locations",
        domain=[('usage', '=', 'internal')])
    category_ids = fields.Many2many(
        'product.category', string="Product Categories")
    product_ids = fields.Many2many('product.product', string="Products")

    # Lignes calculées (affichées dans une page séparée, pas dans le popup)
    line_ids = fields.One2many(
        'inventory.historical.qty.line', 'wizard_id', string="Result")

    # ------------------------------------------------------------------
    # Outils communs aux deux boutons
    # ------------------------------------------------------------------

    def _get_scope_domain(self, location_field='location_id'):
        # Même interface que inventory.audit._get_scope_domain.
        # Filtres combinés avec ET. AUCUN filtre n'est obligatoire :
        # sans filtre, le domaine est vide = tout est inclus.
        self.ensure_one()
        domain = []
        if self.warehouse_id:
            domain.append((
                location_field, 'child_of',
                self.warehouse_id.view_location_id.id))
        if self.location_ids:
            domain.append((location_field, 'child_of', self.location_ids.ids))
        if self.category_ids:
            domain.append((
                'product_id.categ_id', 'child_of', self.category_ids.ids))
        if self.product_ids:
            domain.append(('product_id', 'in', self.product_ids.ids))
        return domain

    def _check_date(self):
        self.ensure_one()
        if self.date > fields.Datetime.now():
            raise UserError(_("The date cannot be in the future."))

    def _get_day_bounds(self):
        # Début et fin (en UTC, comme la base) du JOUR de self.date,
        # calculés dans le fuseau horaire de l'utilisateur.
        self.ensure_one()
        tz = pytz.timezone(
            self.env.context.get('tz') or self.env.user.tz or 'UTC')
        local_day = pytz.utc.localize(self.date).astimezone(tz).date()
        start = tz.localize(datetime.combine(local_day, time.min))
        end = tz.localize(
            datetime.combine(local_day + timedelta(days=1), time.min))

        def to_utc(value):
            return value.astimezone(pytz.utc).replace(tzinfo=None)

        return to_utc(start), to_utc(end)

    def _format_dt(self, value):
        # Affiche une date UTC dans le fuseau de l'utilisateur
        return fields.Datetime.context_timestamp(
            self, value).strftime('%d/%m/%Y %H:%M')

    def _build_line_vals(self, report, period_from, period_to, only_moved):
        # Transforme le rapport du mixin en valeurs de lignes.
        # only_moved=True : on garde seulement les (produit, lieu) qui ont
        # eu au moins un mouvement dans la période.
        Product = self.env['product.product']
        vals_list = []
        for key in sorted(report):
            product_id, location_id, lot_id = key
            data = report[key]
            rounding = Product.browse(product_id).uom_id.rounding

            def is_zero(value, rounding=rounding):
                return float_is_zero(value, precision_rounding=rounding)

            has_moves = not is_zero(data['in']) or not is_zero(data['out'])
            if only_moved and not has_moves:
                continue
            # Ligne sans stock ni mouvement : inutile
            if (not has_moves and is_zero(data['start'])
                    and is_zero(data['end'])):
                continue

            vals_list.append({
                'wizard_id': self.id,
                'product_id': product_id,
                'location_id': location_id,
                'lot_id': lot_id or False,
                'qty_start': data['start'],
                'in_qty': data['in'],
                'out_qty': data['out'],
                'qty_end': data['end'],
                'period_from': period_from,
                'period_to': period_to or False,
            })
        return vals_list

    def _open_result(self, name):
        # Ouvre une PAGE séparée (liste + barre de recherche) avec les
        # lignes de ce wizard. On y filtre par produit, emplacement,
        # catégorie, entrepôt, etc.
        self.ensure_one()
        list_view = self.env.ref(
            'stock_inventory_audit.inventory_historical_qty_line_view_list')
        search_view = self.env.ref(
            'stock_inventory_audit.inventory_historical_qty_line_view_search')
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'inventory.historical.qty.line',
            'views': [(list_view.id, 'list')],
            'search_view_id': search_view.id,
            'domain': [('wizard_id', '=', self.id)],
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Bouton 1 : "Quantity at Date"
    # ------------------------------------------------------------------

    def action_show_quantity(self):
        # Pour chaque (produit, lieu) : quantité à la date choisie, entrées
        # et sorties depuis cette date, et quantité actuelle.
        self.ensure_one()
        self._check_date()

        report = self._get_period_report(
            self.date, False, self.company_id, self._get_scope_domain)
        vals_list = self._build_line_vals(
            report, self.date, False, only_moved=False)
        if not vals_list:
            raise UserError(_("No stock found for this date."))

        self.line_ids.unlink()
        self.env['inventory.historical.qty.line'].create(vals_list)
        return self._open_result(
            _("Quantity at %s (until now)", self._format_dt(self.date)))

    # ------------------------------------------------------------------
    # Bouton 2 : "Moves of the Day"
    # ------------------------------------------------------------------

    def action_show_moves(self):
        # Seulement les (produit, lieu) qui ont eu au moins un mouvement
        # dans la journée choisie, même si d'autres produits du même lieu
        # n'en ont pas eu.
        self.ensure_one()
        self._check_date()

        start, end = self._get_day_bounds()
        report = self._get_period_report(
            start, end, self.company_id, self._get_scope_domain)
        vals_list = self._build_line_vals(report, start, end, only_moved=True)
        if not vals_list:
            raise UserError(_("No stock moves found for this day."))

        self.line_ids.unlink()
        self.env['inventory.historical.qty.line'].create(vals_list)
        return self._open_result(
            _("Moves of the Day %s", self._format_dt(start)[:10]))


class InventoryHistoricalQtyLine(models.TransientModel):
    _name = 'inventory.historical.qty.line'
    _description = "Historical Quantity Line"

    wizard_id = fields.Many2one(
        'inventory.historical.qty.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string="Product")
    # Stockés pour pouvoir filtrer / regrouper dans la barre de recherche
    categ_id = fields.Many2one(
        'product.category', string="Product Category",
        related='product_id.categ_id', store=True)
    location_id = fields.Many2one('stock.location', string="Location")
    warehouse_id = fields.Many2one(
        'stock.warehouse', string="Warehouse",
        related='location_id.warehouse_id', store=True)
    lot_id = fields.Many2one('stock.lot', string="Lot/Serial Number")

    # Quantité au début de la période
    qty_start = fields.Float(
        string="Quantity at Start", digits='Product Unit')
    # Total des entrées pendant la période
    in_qty = fields.Float(string="Incoming", digits='Product Unit')
    # Total des sorties pendant la période
    out_qty = fields.Float(string="Outgoing", digits='Product Unit')
    # Quantité à la fin de la période : début + entrées - sorties
    qty_end = fields.Float(string="Quantity at End", digits='Product Unit')

    # Période de la ligne (utilisée par le bouton "Details")
    period_from = fields.Datetime(string="From")
    period_to = fields.Datetime(string="To")

    move_ids = fields.One2many(
        'inventory.historical.move', 'line_id', string="Moves")

    def action_view_moves(self):
        # Bouton "Details" d'une ligne : ouvre une PAGE avec les mouvements
        # de CE produit, dans CE lieu et CE lot, pendant la période de la
        # ligne, avec les entrées et les sorties dans deux colonnes.
        self.ensure_one()
        wizard = self.wizard_id

        domain = [
            ('state', '=', 'done'),
            ('company_id', '=', wizard.company_id.id),
            ('product_id', '=', self.product_id.id),
            ('lot_id', '=', self.lot_id.id or False),
            ('date', '>', self.period_from),
            '|',
            ('location_id', '=', self.location_id.id),
            ('location_dest_id', '=', self.location_id.id),
        ]
        if self.period_to:
            domain.append(('date', '<=', self.period_to))

        move_lines = self.env['stock.move.line'].search(
            domain, order='date, id')
        if not move_lines:
            raise UserError(_("No moves found for this product in this period."))

        vals_list = []
        for move_line in move_lines:
            qty = move_line.quantity_product_uom
            # Entrée si le stock arrive dans CE lieu, sortie s'il en part
            is_in = move_line.location_dest_id == self.location_id
            vals_list.append({
                'line_id': self.id,
                'date': move_line.date,
                'reference': move_line.reference,
                'product_id': move_line.product_id.id,
                'lot_id': move_line.lot_id.id,
                'location_id': move_line.location_id.id,
                'location_dest_id': move_line.location_dest_id.id,
                'in_qty': qty if is_in else 0.0,
                'out_qty': 0.0 if is_in else qty,
            })

        self.move_ids.unlink()
        self.env['inventory.historical.move'].create(vals_list)

        list_view = self.env.ref(
            'stock_inventory_audit.inventory_historical_move_view_list')
        return {
            'type': 'ir.actions.act_window',
            'name': _("Moves: %s - %s",
                      self.product_id.display_name,
                      self.location_id.complete_name),
            'res_model': 'inventory.historical.move',
            'views': [(list_view.id, 'list')],
            'domain': [('line_id', '=', self.id)],
            'target': 'current',
        }


class InventoryHistoricalMove(models.TransientModel):
    _name = 'inventory.historical.move'
    _description = "Historical Quantity - Move Detail"
    _order = 'date, id'

    line_id = fields.Many2one(
        'inventory.historical.qty.line', required=True, ondelete='cascade')
    date = fields.Datetime(string="Date")
    reference = fields.Char(string="Reference")
    product_id = fields.Many2one('product.product', string="Product")
    lot_id = fields.Many2one('stock.lot', string="Lot/Serial Number")
    location_id = fields.Many2one('stock.location', string="From")
    location_dest_id = fields.Many2one('stock.location', string="To")
    # Deux colonnes séparées : entrées et sorties
    in_qty = fields.Float(string="Incoming", digits='Product Unit')
    out_qty = fields.Float(string="Outgoing", digits='Product Unit')