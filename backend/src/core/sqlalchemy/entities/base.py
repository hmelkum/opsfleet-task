import re

from sqlalchemy.orm import declared_attr


def _pascal_to_lower_snake(name: str) -> str:
    """Convert PascalCase/camelCase to lower_snake_case (PostgreSQL convention).

    Handles acronyms: ``AWSTable`` -> ``aws_table``, ``HTTPServer`` -> ``http_server``.
    """
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.lower()


# PostgreSQL specific
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
}


class _TablenameMixin:
    @declared_attr.directive
    def __tablename__(cls: type) -> str:  # type: ignore
        if not cls.__name__.endswith("Entity"):
            raise ValueError(
                f"Class {cls.__name__} does not end with 'Entity'.\n"
                + " " * len("ValueError: ") +
                "If you are not following 'NamedEntity' naming set '__tablename__' manually."
            )
        tablename = cls.__name__[:-6]
        tablename = _pascal_to_lower_snake(tablename)
        if tablename.endswith("y") and not tablename.endswith(("ay", "ey", "iy", "oy", "uy")):
            return tablename[:-1] + "ies"
        elif tablename.endswith(("s", "x", "z", "ch", "sh")):
            return tablename + "es"
        else:
            return tablename + "s"
