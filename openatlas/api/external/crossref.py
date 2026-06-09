from __future__ import annotations

import requests

from openatlas import app
from openatlas.api.external.base import ExternalApi
from openatlas.display.util import link
from openatlas.models.entity import Entity


class Crossref(ExternalApi):  # pylint: disable=too-few-public-methods

    @staticmethod
    def get_info(id_: str, system: Entity) -> dict[str, object]:
        info: dict[str, object] = {}
        try:
            url = f'https://api.crossref.org/works/{id_}'
            data = requests.get(
                url,
                headers=app.config['USER_AGENT'],
                proxies=app.config['PROXIES'],
                timeout=10).json()
        except Exception:  # pragma: no cover
            return info

        if 'message' not in data:
            return info

        item = data['message']

        if 'title' in item and item['title']:
            info['title'] = item['title'][0]

        if 'author' in item:
            authors = []
            for author in item['author']:
                name = []
                if 'family' in author:
                    name.append(author['family'])
                if 'given' in author:
                    name.append(author['given'])
                authors.append(', '.join(name))
            info['authors'] = '; '.join(authors)

        if 'container-title' in item and item['container-title']:
            info['container'] = item['container-title'][0]

        if 'publisher' in item:
            info['publisher'] = item['publisher']

        # Get year from issued or published-print
        year = None
        for date_field in ['issued', 'published-print', 'published-online']:
            if date_field in item and 'date-parts' in item[date_field]:
                try:
                    year = item[date_field]['date-parts'][0][0]
                    if year:
                        break
                except (IndexError, TypeError):
                    continue
        if year:
            info['year'] = year

        if 'DOI' in item:
            info['DOI'] = link(item['DOI'], f'https://doi.org/{item["DOI"]}',
                               external=True)

        if 'type' in item:
            info['type'] = item['type'].replace('-', ' ').title()

        if 'page' in item:
            info['page'] = item['page']

        if 'volume' in item:
            info['volume'] = item['volume']

        if 'issue' in item:
            info['issue'] = item['issue']

        return info
