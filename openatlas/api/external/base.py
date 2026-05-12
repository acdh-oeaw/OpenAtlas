import abc


class ExternalApi(abc.ABC):  # pylint: disable=too-few-public-methods

    @staticmethod
    @abc.abstractmethod
    def get_info(id_: str) -> dict[str, object]:
        """Fetch data from an external reference system"""
