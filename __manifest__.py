{
    'name': "Stock Inventory Audit",
    'summary': "Document-based inventory audit workflow for Odoo 19",
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'license': 'LGPL-3',
    'author': "khouloud wiam",
    'depends': ['stock', 'product'],

    # Fichiers chargés à l'installation, DANS CET ORDRE
        'data': [
        'security/ir.model.access.csv',
        'data/inventory_audit_sequence.xml',
        'views/inventory_audit_revert_wizard_views.xml',
        'views/inventory_historical_qty_wizard_views.xml',
        'views/inventory_audit_views.xml',
    ],

    'installable': True,
    'application': True,
}
