# -*- coding: utf-8 -*-

# Copyright(C) 2016      Edouard Lambert
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


from weboob.exceptions import  BrowserIncorrectPassword
from weboob.browser import LoginBrowser, URL, need_login

from .pages import LoginPage, AccountsPage, FCPEInvestmentPage, CCBInvestmentPage, HistoryPage


class CmesBrowser(LoginBrowser):
    login = URL('(?P<subsite>.*)fr/identification/default.cgi', LoginPage)
    accounts = URL('(?P<subsite>.*)fr/espace/devbavoirs.aspx\?mode=net&menu=cpte$', AccountsPage)
    fcpe_investment = URL('(?P<subsite>.*)fr/.*GoPositionsParFond.*', FCPEInvestmentPage)
    ccb_investment = URL('(?P<subsite>.*)fr/.*GoCCB.*', CCBInvestmentPage)
    history = URL('(?P<subsite>.*)fr/espace/devbavoirs.aspx\?mode=net&menu=cpte&page=operations',
                  '(?P<subsite>.*)fr/.*GoOperationsTraitees',
                  '(?P<subsite>.*)fr/.*GoOperationDetails', HistoryPage)

    def __init__(self, website, username, password, subsite="", *args, **kwargs):
        super(LoginBrowser, self).__init__(*args, **kwargs)
        self.BASEURL = website
        self.username = username
        self.password = password
        self.subsite = subsite

    def do_login(self):
        self.login.go(subsite=self.subsite).login(self.username, self.password)

        if self.login.is_here():
            raise BrowserIncorrectPassword

    @need_login
    def iter_accounts(self):
        return self.accounts.stay_or_go(subsite=self.subsite).iter_accounts()

    @need_login
    def iter_investment(self, account):
        fcpe_link = self.accounts.stay_or_go(subsite=self.subsite).get_investment_link()
        ccb_link = self.page.get_pocket_link()

        if fcpe_link or ccb_link:
            return self._iter_investment(fcpe_link, ccb_link)
        else:
            return []

    def _iter_investment(self, fcpe_link, ccb_link):
        if fcpe_link:
            for inv in self.location(fcpe_link).page.iter_investment():
                yield inv

        if ccb_link:
            for inv in self.location(ccb_link).page.iter_investment():
                yield inv

    @need_login
    def iter_pocket(self, account):
        ccb_link = self.accounts.stay_or_go(subsite=self.subsite).get_pocket_link()
        for inv in self.location(ccb_link).page.iter_investment():
            for poc in self.page.iter_pocket(inv=inv):
                yield poc

    @need_login
    def iter_history(self, account):
        link = self.history.go(subsite=self.subsite).get_link()
        if link:
            return self.location(link).page.iter_history()
        return iter([])
