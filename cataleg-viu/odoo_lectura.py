"""Lectura d'Odoo STAGING (només lectura: llista blanca de mètodes, assert de Staging; connexió per variables d'entorn)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "grups-odoo", "scripts"))
from odoo_env import crida_lectura as lectura, LECTURA  # noqa: E402,F401
