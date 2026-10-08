# Outils Odoo : api (décorateurs), fields (champs), models (classe de base)
from odoo import api, fields, models


class StockMove(models.Model):
    # _inherit (sans _name) : on ÉTEND le modèle existant stock.move d'Odoo
    _inherit = 'stock.move'

    # Lien direct vers l'audit qui a généré ce mouvement de stock
    # copy=False : non copié si on duplique / index=True : recherche rapide
    # readonly=True : rempli uniquement par le code, jamais à la main
    inventory_audit_id = fields.Many2one(
        'inventory.audit', string="Inventory Audit",
        copy=False, index=True, readonly=True)

    # NOUVEAU : gain ou perte, calculé à partir du sens du mouvement
    # utilisé pour colorer la liste dans le smart button (vert/rouge)
    audit_move_type = fields.Selection([
        ('gain', "Gain"),
        ('loss', "Loss"),
    ], string="Audit Move Type", compute='_compute_audit_move_type')

    # Se recalcule quand l'emplacement source ou destination change
    @api.depends('location_id.usage', 'location_dest_id.usage')
    def _compute_audit_move_type(self):
        # Boucle sur chaque mouvement
        for move in self:
            # Le stock entre depuis l'emplacement virtuel -> c'est un gain
            if (move.location_dest_id.usage == 'internal'
                    and move.location_id.usage == 'inventory'):
                move.audit_move_type = 'gain'
            # Le stock sort vers l'emplacement virtuel -> c'est une perte
            elif (move.location_id.usage == 'internal'
                    and move.location_dest_id.usage == 'inventory'):
                move.audit_move_type = 'loss'
            # Mouvement classique (livraison, réception...) : ni l'un ni l'autre
            else:
                move.audit_move_type = False
                