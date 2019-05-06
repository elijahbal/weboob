# -*- coding: utf-8 -*-

# Copyright(C) 2016      Edouard Lambert
#
# This file is part of a weboob module.
#
# This weboob module is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This weboob module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this weboob module. If not, see <http://www.gnu.org/licenses/>.

from __future__ import unicode_literals


import re

from weboob.browser.pages import HTMLPage, LoggedPage
from weboob.browser.elements import ListElement, ItemElement, method
from weboob.browser.filters.standard import (
    CleanText, Capitalize, Format, Date, Regexp, CleanDecimal, Env, Currency, Field, Eval,
    Coalesce,
)
from weboob.capabilities.bank import Investment, Transaction
from weboob.capabilities.base import NotAvailable
from weboob.exceptions import ActionNeeded, BrowserUnavailable
from weboob.tools.compat import urljoin
from weboob.tools.capabilities.bank.investments import is_isin_valid


def MyDecimal(*args, **kwargs):
    kwargs.update(replace_dots=True, default=NotAvailable)
    return CleanDecimal(*args, **kwargs)


class BasePage(HTMLPage):
    def on_load(self):
        super(BasePage, self).on_load()

        if 'Erreur' in CleanText('//div[@id="main"]/h1', default='')(self.doc):
            err = CleanText('//div[@id="main"]/div[@class="content"]', default='Site indisponible')(self.doc)
            raise BrowserUnavailable(err)


class PrevoyancePage(LoggedPage, HTMLPage):
    pass


class LoginPage(BasePage, HTMLPage):
    def login(self, login, password):
        form = self.get_form(id="loginForm")
        form['username'] = login
        form['password'] = password
        form.submit()


class InvestmentPage(LoggedPage, HTMLPage):
    @method
    class fill_account(ItemElement):
        obj_balance = MyDecimal('//ul[has-class("m-data-group")]//strong')
        obj_currency = Currency('//ul[has-class("m-data-group")]//strong')
        obj_valuation_diff = MyDecimal('//h3[contains(., "value latente")]/following-sibling::p[1]')

    def get_history_link(self):
        history_link = self.doc.xpath('//li/a[contains(text(), "Historique")]/@href')
        return urljoin(self.browser.BASEURL, history_link[0]) if history_link else ''

    def unavailable_details(self):
        return CleanText('//p[contains(text(), "est pas disponible")]')(self.doc)

    @method
    class iter_investment(ListElement):
        item_xpath = '//div[contains(@class, "m-table")]/table/tbody/tr[not(has-class("total"))]'

        class item(ItemElement):
            klass = Investment

            def condition(self):
                return self.obj_label not in ('Total', '')

            obj_quantity = MyDecimal('./td[@data-label="Nombre de parts"]', default=NotAvailable)
            obj_unitvalue = MyDecimal('./td[@data-label="Valeur de la part"]')
            obj_valuation = MyDecimal('./td[@data-label="Valeur de rachat"]', default=NotAvailable)
            obj_vdate = Date(
                CleanText('./td[@data-label="Date de valeur"]'), dayfirst=True, default=NotAvailable
            )

            obj_label = Coalesce(
                CleanText('./th[@data-label="Nom du support"]/a'),
                CleanText('./th[@data-label="Nom du support"]'),
                CleanText('./td[@data-label="Nom du support"]'),
            )

            def obj_code(self):
                code = re.search(r'"(.*)"', CleanText('./th[@data-label="Nom du support"]/a/@onclick')(self))
                if code and is_isin_valid(code.group(1)):
                    return code.group(1)
                return NotAvailable

            def obj_code_type(self):
                if Field('code')(self) != NotAvailable:
                    return Investment.CODE_TYPE_ISIN
                return NotAvailable


class InvestmentElement(ItemElement):
    klass = Investment

    obj_label = CleanText('./div[@data-label="Nom du support" or @data-label="Support cible"]/span[1]')
    obj_quantity = MyDecimal('./div[contains(@data-label, "Nombre")]')
    obj_unitvalue = MyDecimal('./div[contains(@data-label, "Valeur")]')
    obj_valuation = MyDecimal('./div[contains(@data-label, "Montant")]')
    obj_vdate = Env('date')


class TransactionElement(ItemElement):
    klass = Transaction

    obj_label = Format('%s du %s', Field('_labeltype'), Field('date'))
    obj_date = Date(
        Regexp(CleanText('./ancestor::div[@class="onerow" or starts-with(@id, "term") or has-class("grid")]/'
                         'preceding-sibling::h3[1]//div[contains(text(), "Date")]'),
               r'(\d{2}\/\d{2}\/\d{4})'),
        dayfirst=True)
    obj_type = Transaction.TYPE_BANK

    obj_amount = MyDecimal('./ancestor::div[@class="onerow" or starts-with(@id, "term") or has-class("grid")]/'
                           'preceding-sibling::h3[1]//div[has-class("montant-mobile")]', default=NotAvailable)

    obj__labeltype = Regexp(Capitalize('./preceding::h2[@class="feature"][1]'),
                            r'Historique Des\s+(\w+)')

    def obj_investments(self):
        return list(self.iter_investments(self.page, parent=self))

    @method
    class iter_investments(ListElement):
        item_xpath = './div[@class="line"]'

        class item(InvestmentElement):
            pass

    def parse(self, el):
        self.env['date'] = Field('date')(self)


class HistoryPage(LoggedPage, HTMLPage):
    @method
    class iter_versements(ListElement):
        item_xpath = '//div[contains(@id, "versementProgramme3") or contains(@id, "versementLibre3")]/h2'

        class item(ItemElement):
            klass = Transaction
            obj_date = Date(
                Regexp(CleanText('./div[1]'), r'(\d{2}\/\d{2}\/\d{4})'),
                dayfirst=True
            )
            obj_amount = Eval(lambda x: x / 100, CleanDecimal('./div[2]'))
            obj_label = Format(
                '%s %s',
                CleanText('./preceding::h3[1]'),
                Regexp(CleanText('./div[1]'), r'(\d{2}\/\d{2}\/\d{4})')
            )

            def obj_investments(self):
                investments = []

                for elem in self.xpath('./following-sibling::div[1]//ul'):
                    inv = Investment()
                    inv.label = CleanText('./li[1]/p')(elem)
                    inv.portfolio_share = CleanDecimal('./li[2]/p', replace_dots=True, default=NotAvailable)(elem)
                    inv.quantity = CleanDecimal('./li[3]/p', replace_dots=True, default=NotAvailable)(elem)
                    inv.valuation = CleanDecimal('./li[4]/p', replace_dots=True)(elem)
                    investments.append(inv)

                return investments

    @method
    class iter_arbitrages(ListElement):
        item_xpath = '//div[contains(@id, "arbitrageLibre3")]/h2'

        class item(ItemElement):
            klass = Transaction
            obj_date = Date(
                Regexp(CleanText('.//div[1]'), r'(\d{2}\/\d{2}\/\d{4})'),
                dayfirst=True
            )
            obj_label = Format(
                '%s %s',
                CleanText('./preceding::h3[1]'),
                Regexp(CleanText('./div[1]'), r'(\d{2}\/\d{2}\/\d{4})')
            )

            def obj_amount(self):
                return sum(x.valuation for x in Field('investments')(self))

            def obj_investments(self):
                investments = []
                for elem in self.xpath('./following-sibling::div[1]//tbody/tr'):
                    inv = Investment()
                    inv.valuation = CleanDecimal('./td[2]/p', replace_dots=True)(elem)
                    inv.label = CleanText('./td[1]')(elem)
                    investments.append(inv)

                return investments


class ActionNeededPage(LoggedPage, HTMLPage):
    def on_load(self):
        raise ActionNeeded('Veuillez mettre à jour vos coordonnées')


class ValidationPage(LoggedPage, HTMLPage):
    def on_load(self):
        error_message = CleanText('//p[@id="errorSigned"]')(self.doc)
        if error_message:
            raise ActionNeeded(error_message)


class InvestDetailPage(LoggedPage, HTMLPage):
    @method
    class fill_investment(ItemElement):
        obj_unitprice = CleanDecimal('//td[@class="donnees"]/span[@id="VL_achat"]', default=NotAvailable)
        obj_diff_percent = Eval(lambda x: x / 100, CleanDecimal('//td[@class="donnees"]/span[@id="Performance"]', default=NotAvailable))
        obj_description = CleanText('//td[@class="donnees"]/span[@id="Nature"]', default=NotAvailable)