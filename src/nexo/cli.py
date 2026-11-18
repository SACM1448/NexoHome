"""Operaciones locales explícitas; nunca recibe contraseñas por argumentos."""

import argparse
import getpass
import os
import sys
import warnings

from sqlalchemy.exc import SQLAlchemyError

from nexo.config import Settings
from nexo.database import Database


def main():
    parser = argparse.ArgumentParser(description="Administración local de NEXO Home")
    parser.add_argument("command", choices=["migrate", "init-admin", "serve"])
    args = parser.parse_args()
    database = None
    try:
        os.umask(0o077)
        database = Database(Settings.from_env().data_dir)
        if args.command in {"migrate", "serve"}:
            database.migrate()
        if args.command == "init-admin":
            from nexo.database import administrators
            from sqlalchemy import select
            database.check()
            with database.transaction() as db:
                if db.scalar(select(administrators.c.id)) is not None:
                    raise ValueError("Ya existe un administrador; inicialización rechazada")
            username = input("Usuario administrador: ").strip()
            # Fallar cerrado si getpass no puede garantizar entrada sin eco.
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("Contraseña (12–128 caracteres, letras y números): ")
                confirmation = getpass.getpass("Confirmar contraseña: ")
            if password != confirmation:
                raise ValueError("Las contraseñas no coinciden")
            from nexo.security import initialize_admin
            initialize_admin(database, username, password)
            print("Administrador inicial creado")
        if args.command == "serve":
            database.close()
            os.execvp(sys.executable, [sys.executable, "-m", "uvicorn", "nexo.main:app",
                                      "--host", "0.0.0.0", "--port", "8000", "--workers", "1",
                                      "--limit-concurrency", "64", "--timeout-keep-alive", "5",
                                      "--no-proxy-headers", "--no-access-log"])
    except (ValueError, getpass.GetPassWarning) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (SQLAlchemyError, OSError, RuntimeError):
        print("Persistencia no disponible; comprueba permisos y migraciones", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Inicialización cancelada", file=sys.stderr)
        return 1
    finally:
        if database:
            database.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
