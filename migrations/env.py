from alembic import context
from sqlalchemy import engine_from_config, pool

from wms2ship.config import Settings

config = context.config
# Application startup supplies an explicit URL. CLI uses WMS_DATA_DIR.
if config.get_main_option("sqlalchemy.url") == "sqlite:///data/app.sqlite3":
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if context.is_offline_mode():
    context.configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = engine_from_config(
        config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
