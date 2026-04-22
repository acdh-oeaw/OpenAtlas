import abc


class ExternalApi(abc.ABC):

    @staticmethod
    @abc.abstractmethod
    def get_info(id_: str) -> dict[str, object]:
        pass
