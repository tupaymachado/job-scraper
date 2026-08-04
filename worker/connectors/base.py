"""Interface de conector.

Adicionar uma fonte nova (Gupy, Remotive, InfoJobs) = um arquivo novo aqui
que implemente `search()` e se registre em REGISTRY. O pipeline não muda.
"""

from __future__ import annotations

from typing import Callable, Protocol

from models import RawJob, SearchProfile


class Connector(Protocol):
    name: str

    def search(self, profile: SearchProfile, limit: int = 50) -> list[RawJob]:
        """Retorna vagas da fonte para esse perfil de busca.

        Deve levantar SourceBlocked quando a fonte bloquear, em vez de
        retornar vazio silenciosamente — o orquestrador distingue
        'nada novo' de 'fomos barrados'.
        """
        ...


REGISTRY: dict[str, Callable[[], Connector]] = {}


def register(name: str) -> Callable[[Callable[[], Connector]], Callable[[], Connector]]:
    def deco(factory: Callable[[], Connector]) -> Callable[[], Connector]:
        REGISTRY[name] = factory
        return factory

    return deco


def get_connector(name: str) -> Connector:
    if name not in REGISTRY:
        raise KeyError(f"conector desconhecido: {name!r}. Disponíveis: {sorted(REGISTRY)}")
    return REGISTRY[name]()
