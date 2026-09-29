"""Budget-specific migration steps; no Result or observation DB access."""

from .budget_registry import BudgetRegistry, RegistryError, SCHEMA_VERSION
from .db_migrations import Migration, MigrationError


class BudgetMigrationBackend:
    kind = "budget"
    target_version = SCHEMA_VERSION
    migrations = (
        Migration("budget-0001-empty-prototype", 1, 3, BudgetRegistry._migrate_empty_to_three),
        Migration("budget-0002-configured-targets", 2, 3, BudgetRegistry._migrate_empty_to_three),
        Migration("budget-0003-execution-targets", 3, 4, BudgetRegistry._migrate_targets),
    )

    def __init__(self, path, key_file):
        self.registry = BudgetRegistry(path, key_file)
        self.storage = self.registry.storage

    def copy_at(self, path):
        return type(self)(path, self.storage.key_file)

    def status(self, conn):
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"registry_meta", "budgets", "connections", "execution_accounts", "destinations", "registry_history"} <= tables:
            raise MigrationError("Database is not a recognized Budget registry")
        rows = conn.execute("SELECT schema_version, revision FROM registry_meta WHERE singleton=1").fetchall()
        if len(rows) != 1:
            raise MigrationError("Invalid Budget registry metadata")
        version, revision = rows[0]
        if type(version) is not int or type(revision) is not int or revision < 0:
            raise MigrationError("Invalid Budget registry metadata")
        history = ([dict(row) for row in conn.execute("SELECT * FROM db_migration_history ORDER BY target_version")]
                   if "db_migration_history" in tables else [])
        return dict(kind=self.kind, schema_version=version, revision=revision,
                    readable_versions=[3, 4], writable_versions=[3, 4],
                    readable=version in (3, 4), writable=version in (3, 4), migrations=history)

    def preflight(self, conn):
        self.storage._check_connection(conn)
        version = self.status(conn)["schema_version"]
        if version in (1, 2):
            managers = "budget_members" if version == 1 else "budget_managers"
            if self.status(conn)["revision"] != 0 or any(
                    conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                    for table in ("budgets", managers, "connections", "execution_accounts", "destinations", "registry_history")):
                raise MigrationError("Populated prototypes require a separately reviewed migration")
        elif version in (3, 4):
            self._verify_relationships(conn, version)
        else:
            raise MigrationError("Unsupported Budget schema version")

    @staticmethod
    def _verify_relationships(conn, version):
        if conn.execute("""SELECT 1 FROM destinations d JOIN budgets b ON b.id=d.budget_id
                JOIN execution_accounts a ON a.id=d.account_id
                WHERE b.system<>a.system OR (?=3 AND d.system<>b.system) LIMIT 1""", (version,)).fetchone():
            raise RegistryError("Existing destination systems are inconsistent")
        if version == 4:
            if conn.execute("""SELECT 1 FROM budget_defaults g JOIN budgets b ON b.id=g.id
                    JOIN execution_accounts a ON a.id=g.account_id WHERE b.system<>a.system
                    UNION ALL SELECT 1 FROM budget_defaults g JOIN destinations d ON d.budget_id=g.id
                    WHERE g.allocation_project_id<>d.allocation_project_id LIMIT 1""").fetchone():
                raise MigrationError("Budget common settings are inconsistent")

    def verify(self, conn):
        self.preflight(conn)
        if self.status(conn)["schema_version"] not in (3, 4):
            raise MigrationError("Budget schema is not supported for application use")
