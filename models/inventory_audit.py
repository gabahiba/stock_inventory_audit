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
    # Récupère _get_historical_quantities (calcul de la quantité à une
    # date), partagé avec l'écran "Historical Quantity"
    _inherit = ['inventory.historical.mixin']
    _description = "Inventory Audit"
    _order = 'audit_date desc, id desc'

    # ------------------------------------------------------------------
    # Champs de l'en-tête
    # ------------------------------------------------------------------

    name = fields.Char(
        string="Reference", required=True, copy=False,
        default=lambda self: _("New Inventory Audit"))

    # DATE DU COMPTAGE physique.
    # La quantité théorique est calculée à cette date précise.
    # (nom technique inchangé pour ne pas casser la base ni les vues)
    audit_date = fields.Datetime(
        string="Count Date", required=True, default=fields.Datetime.now,
        help="Date and time of the physical count. The theoretical "
             "quantity is computed as of this moment.")

    # Date à laquelle l'audit est appliqué sur le stock
    # (remplie automatiquement au clic sur "Validate Inventory")
    validation_date = fields.Datetime(
        string="Validation Date", readonly=True, copy=False,
        help="Date on which the audit was applied to the stock.")

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
    # Périmètre : domaine de recherche
    # ------------------------------------------------------------------

    def _get_scope_domain(self, location_field='location_id'):
        # Domaine du périmètre (cases cochées combinées avec OR).
        # location_field permet de l'appliquer sur stock.quant (location_id)
        # ou sur stock.move.line (location_id OU location_dest_id).
        self.ensure_one()
        scope_domains = []

        if self.scope_warehouse:
            if not self.warehouse_id:
                raise UserError(_("Please select a warehouse."))
            scope_domains.append([(
                location_field, 'child_of',
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
                location_field, 'child_of', self.location_ids.ids)])

        if not scope_domains:
            raise UserError(_("Please select at least one audit scope."))

        return expression.OR(scope_domains)

    # ------------------------------------------------------------------
    # Quantité à la date du comptage -> lignes d'audit
    # ------------------------------------------------------------------

    def _get_historical_lines_vals(self):
        # Utilise la méthode du mixin (la même que l'écran
        # "Historical Quantity") avec la date du comptage.
        # Appelée par : action_start
        # Retourne : liste de dicts prêts pour inventory.audit.line.create
        self.ensure_one()
        quantities = self._get_historical_quantities(
            self.audit_date, self.company_id, self._get_scope_domain)

        Product = self.env['product.product']
        vals_list = []
        for key in sorted(quantities):
            product_id, location_id, lot_id = key
            # quantities[key] = (quantité actuelle, quantité à la date)
            historical = quantities[key][1]
            rounding = Product.browse(product_id).uom_id.rounding
            if float_is_zero(historical, precision_rounding=rounding):
                continue
            vals_list.append({
                'audit_id': self.id,
                'product_id': product_id,
                'location_id': location_id,
                'lot_id': lot_id or False,
                # Quantité du système À LA DATE DU COMPTAGE
                'theoretical_qty': historical,
                # Par défaut = théorique (le personnel saisit ensuite)
                'counted_qty': historical,
            })
        return vals_list

    # ------------------------------------------------------------------
    # Bouton "Historical Quantity" -> ouvre le popup de calcul
    # ------------------------------------------------------------------

    def action_open_historical_qty(self):
        # Aperçu seulement : ne crée aucune ligne, ne change pas le statut
        # et ne touche pas au stock.
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Historical Quantity"),
            'res_model': 'inventory.historical.qty.wizard',
            'view_mode': 'form',
            'target': 'new',
            # La date du popup est pré-remplie avec la date du comptage
            'context': {
                'default_date': fields.Datetime.to_string(self.audit_date),
                'default_company_id': self.company_id.id,
            },
        }

    # ------------------------------------------------------------------
    # Bouton "Start Inventory"
    # ------------------------------------------------------------------

    def action_start(self):
        for audit in self:
            if audit.state != 'draft':
                raise UserError(_("Only a draft audit can be started."))

            if audit.audit_date > fields.Datetime.now():
                raise UserError(_("The count date cannot be in the future."))

            # Lignes basées sur la quantité à la date du comptage
            vals_list = audit._get_historical_lines_vals()
            if not vals_list:
                raise UserError(_("No stock found for the selected scope."))

            audit.line_ids.unlink()
            self.env['inventory.audit.line'].create(vals_list)
            audit.state = 'in_progress'

    # ------------------------------------------------------------------
    # Bouton "Refresh" : met à jour les lignes avec les opérations
    # faites depuis le démarrage de l'audit
    # ------------------------------------------------------------------

    def action_refresh(self):
        # Pour chaque ligne :
        #   nouvelle théorique = quantité ACTUELLE du système
        #   variation          = nouvelle théorique - ancienne théorique
        #   comptée            = comptée + variation
        # La différence (comptée - théorique) reste donc la même : seules
        # les opérations faites depuis le démarrage sont ajoutées aux
        # deux quantités. Exemple : 70 / 60 (diff -10), puis vente de 10
        # -> Refresh -> 60 / 50 (diff -10).
        # Peut être cliqué plusieurs fois sans risque (sans nouvelle
        # opération, la variation est 0).
        Product = self.env['product.product']
        for audit in self:
            if audit.state != 'in_progress':
                raise UserError(_("Only an audit in progress can be refreshed."))

            # Quantités ACTUELLES du système par (produit, lieu, lot).
            # [0] = quantité actuelle (le mixin renvoie (actuelle, à la date))
            quantities = audit._get_historical_quantities(
                fields.Datetime.now(), audit.company_id,
                audit._get_scope_domain)
            current = {key: values[0] for key, values in quantities.items()}

            # 1) Lignes existantes : on décale théorique ET comptée
            existing_keys = set()
            for line in audit.line_ids:
                key = (line.product_id.id, line.location_id.id, line.lot_id.id)
                existing_keys.add(key)

                new_theoretical = current.get(key, 0.0)
                delta = new_theoretical - line.theoretical_qty

                rounding = line.product_id.uom_id.rounding
                if float_is_zero(delta, precision_rounding=rounding):
                    continue

                line.write({
                    'theoretical_qty': new_theoretical,
                    'counted_qty': line.counted_qty + delta,
                })

            # 2) Nouveau stock apparu dans le périmètre depuis le démarrage
            #    (ex. réception dans un emplacement sans ligne) : on crée
            #    la ligne avec comptée = théorique (différence 0)
            new_vals = []
            for key, qty in sorted(current.items()):
                if key in existing_keys:
                    continue
                product_id, location_id, lot_id = key
                rounding = Product.browse(product_id).uom_id.rounding
                if float_is_zero(qty, precision_rounding=rounding):
                    continue
                new_vals.append({
                    'audit_id': audit.id,
                    'product_id': product_id,
                    'location_id': location_id,
                    'lot_id': lot_id or False,
                    'theoretical_qty': qty,
                    'counted_qty': qty,
                })

            if new_vals:
                self.env['inventory.audit.line'].create(new_vals)

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

        # Le mouvement est daté du jour de la VALIDATION (et non de la
        # date du comptage) : l'historique passé des stocks et les
        # rapports anciens ne changent donc pas.
        move.write({'date': self.validation_date})
        move.move_line_ids.write({'date': self.validation_date})

    def action_validate(self):
        for audit in self:
            if audit.state != 'in_progress':
                raise UserError(_("Only an audit in progress can be validated."))

            # Date d'application de l'audit sur le stock
            audit.validation_date = fields.Datetime.now()

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