# -*- coding: utf-8 -*-

# Copyright(C) 2013      Bezleputh
#
# This file is part of weboob.
#
# weboob is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# weboob is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with weboob. If not, see <http://www.gnu.org/licenses/>.


from weboob.tools.backend import BaseBackend
from weboob.capabilities.job import ICapJob
from .browser import AdeccoBrowser


__all__ = ['AdeccoBackend']


class AdeccoBackend(BaseBackend, ICapJob):
    NAME = 'adecco'
    DESCRIPTION = u'adecco website'
    MAINTAINER = u'Bezleputh'
    EMAIL = 'carton_ben@yahoo.fr'
    VERSION = '0.g'

    BROWSER = AdeccoBrowser

    def search_job(self, pattern=None):
        with self.browser:
            for advert in self.browser.search_job(pattern):
                yield advert

    def get_job_advert(self, _id, advert):
        with self.browser:
            return self.browser.get_job_advert(_id, advert)
