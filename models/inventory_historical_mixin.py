from collections import defaultdict

from odoo import models
from odoo.osv import expression


class InventoryHistoricalMixin(models.AbstractModel):
    # AbstractModel : pas de table en base, juste du code partagé.
    # Les modèles qui font _inherit = ['inventory.historical.mixin']
    # récupèrent les méthodes ci-dessous.
    _name = 'inventory.historical.mixin'
    _description = "Historical Quantity Computation"

    # ------------------------------------------------------------------
    # Totaux des mouvements (entrées / sorties) par (produit, lieu, lot)
    # ------------------------------------------------------------------

    def _get_move_totals(self, date_domain, company, scope_domain_fn):
        # Somme des mouvements TERMINÉS qui respectent date_domain :
        #   entrées : mouvements dont la DESTINATION est un lieu interne
        #   sorties : mouvements dont la SOURCE est un lieu interne
        # Retourne deux dicts : (entrées, sorties)
        #   clé = (product_id, location_id, lot_id)
        MoveLine = self.env['stock.move.line']
        base = [
            ('state', '=', 'done'),
            ('company_id', '=', company.id),
        ] + date_domain

        totals_in = defaultdict(float)
        totals_out = defaultdict(float)

        in_domain = expression.AND([
            base,
            [('location_dest_id.usage', '=', 'internal')],
            scope_domain_fn('location_dest_id'),
        ])
        for product, location, lot, qty in MoveLine._read_group(
                in_domain,
                groupby=['product_id', 'location_dest_id', 'lot_id'],
                aggregates=['quantity_product_uom:sum']):
            totals_in[(product.id, location.id, lot.id)] += qty

        out_domain = expression.AND([
            base,
            [('location_id.usage', '=', 'internal')],
            scope_domain_fn('location_id'),
        ])
        for product, location, lot, qty in MoveLine._read_group(
                out_domain,
                groupby=['product_id', 'location_id', 'lot_id'],
                aggregates=['quantity_product_uom:sum']):
            totals_out[(product.id, location.id, lot.id)] += qty

        return totals_in, totals_out

    # ------------------------------------------------------------------
    # Rapport sur une période
    # ------------------------------------------------------------------

    def _get_period_report(self, date_from, date_to, company, scope_domain_fn):
        # Pour la période ]date_from, date_to] (date_to vide = jusqu'à
        # maintenant), calcule pour chaque (produit, lieu, lot) :
        #
        #   start = quantité au début de la période
        #   in    = total des entrées pendant la période
        #   out   = total des sorties pendant la période
        #   end   = quantité à la fin de la période
        #
        # et toujours :  start + in - out = end
        #
        # date_from       : début (exclu)
        # date_to         : fin (incluse) ou False pour "maintenant"
        # scope_domain_fn : fonction(location_field) -> domaine du périmètre
        #
        # Retourne : {(product_id, location_id, lot_id):
        #             {'start': .., 'in': .., 'out': .., 'end': ..}}
        StockQuant = self.env['stock.quant']

        # 1) Quantités ACTUELLES par (produit, emplacement, lot)
        quant_domain = expression.AND([
            [('location_id.usage', '=', 'internal'),
             ('company_id', '=', company.id)],
            scope_domain_fn('location_id'),
        ])
        current = {}
        for product, location, lot, qty in StockQuant._read_group(
                quant_domain,
                groupby=['product_id', 'location_id', 'lot_id'],
                aggregates=['quantity:sum']):
            current[(product.id, location.id, lot.id)] = qty

        # 2) Mouvements PENDANT la période
        date_domain = [('date', '>', date_from)]
        if date_to:
            date_domain.append(('date', '<=', date_to))
        period_in, period_out = self._get_move_totals(
            date_domain, company, scope_domain_fn)

        # 3) Mouvements APRÈS la période (pour remonter de "maintenant"
        #    jusqu'à la fin de la période)
        after_in, after_out = {}, {}
        if date_to:
            after_in, after_out = self._get_move_totals(
                [('date', '>', date_to)], company, scope_domain_fn)

        # 4) Assemblage
        keys = (set(current) | set(period_in) | set(period_out)
                | set(after_in) | set(after_out))
        report = {}
        for key in keys:
            in_qty = period_in.get(key, 0.0)
            out_qty = period_out.get(key, 0.0)
            after_net = after_in.get(key, 0.0) - after_out.get(key, 0.0)
            end_qty = current.get(key, 0.0) - after_net
            report[key] = {
                'start': end_qty - (in_qty - out_qty),
                'in': in_qty,
                'out': out_qty,
                'end': end_qty,
            }
        return report

    # ------------------------------------------------------------------
    # Utilisé par l'audit (Start / Refresh)
    # ------------------------------------------------------------------

    def _get_historical_quantities(self, date, company, scope_domain_fn):
        # Quantité à une date donnée :
        #   qté à la date = qté actuelle - mouvements nets faits APRÈS la date
        #
        # Retourne : {(product_id, location_id, lot_id): (actuelle, à la date)}
        report = self._get_period_report(date, False, company, scope_domain_fn)
        return {
            key: (values['end'], values['start'])
            for key, values in report.items()
        }