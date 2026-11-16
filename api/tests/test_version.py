import asyncio
import os
import unittest
from unittest import mock

from cerebro.api import main


class VersionEnSalud(unittest.TestCase):
    def test_version_corta_desde_el_entorno(self):
        with mock.patch.dict(os.environ, {"CODIGO_VERSION": "f13d2aa4f39c41150577e59dca3a84e4a0ce8f9d"}):
            self.assertEqual(asyncio.run(main.salud())["version"], "f13d2aa")

    def test_sin_version_dice_desconocida(self):
        e = {k: v for k, v in os.environ.items() if k != "CODIGO_VERSION"}
        with mock.patch.dict(os.environ, e, clear=True):
            self.assertEqual(asyncio.run(main.salud())["version"], "desconocida")


if __name__ == "__main__":
    unittest.main()
