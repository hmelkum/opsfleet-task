from typing import Any

from fastapi import Depends


def _placeholder() -> None:
    raise NotImplementedError(
        "This function is a placeholder and should be "
        "replaced with an actual dependency injection implementation."
    )


def InjectPlaceholder() -> Any:
    return Depends(_placeholder, use_cache=False)


def Inject() -> Any:
    return Depends(use_cache=False)


def InjectScoped() -> Any:
    return Depends(use_cache=True)