# -*- coding: utf-8 -*-

# Copyright(C) 2010-2011 Nicolas Duhamel
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

import os
import time
from datetime import datetime, timedelta

from requests.exceptions import HTTPError

from weboob.browser import LoginBrowser, URL, need_login
from weboob.browser.browsers import StatesMixin
from weboob.browser.exceptions import ServerError
from weboob.capabilities.base import NotAvailable
from weboob.exceptions import (
    BrowserIncorrectPassword, BrowserBanned, NoAccountsException,
    BrowserUnavailable, ActionNeeded, NeedInteractiveFor2FA,
    BrowserQuestion, AppValidation, AppValidationCancelled, AppValidationExpired,
)
from weboob.tools.compat import urlsplit, urlunsplit, parse_qsl
from weboob.tools.decorators import retry

from .pages import (
    LoginPage, Initident, CheckPassword, repositionnerCheminCourant, BadLoginPage, AccountDesactivate,
    AccountList, AccountHistory, CardsList, UnavailablePage, AccountRIB, Advisor,
    TransferChooseAccounts, CompleteTransfer, TransferConfirm, TransferSummary, CreateRecipient, ValidateRecipient,
    ValidateCountry, ConfirmPage, RcptSummary, SubscriptionPage, DownloadPage, ProSubscriptionPage, RevolvingAttributesPage,
    TwoFAPage, Validated2FAPage, SmsPage, DecoupledPage
)
from .pages.accounthistory import (
    LifeInsuranceInvest, LifeInsuranceHistory, LifeInsuranceHistoryInv, RetirementHistory,
    SavingAccountSummary, CachemireCatalogPage,
)
from .pages.accountlist import (
    MarketLoginPage, UselessPage, ProfilePage, MarketCheckPage, MarketHomePage,
)
from .pages.pro import RedirectPage, ProAccountsList, ProAccountHistory, DownloadRib, RibPage
from .pages.mandate import MandateAccountsList, PreMandate, PreMandateBis, MandateLife, MandateMarket
from .linebourse_browser import LinebourseBrowser

from weboob.capabilities.bank import Account, Recipient, AddRecipientStep
from weboob.tools.value import Value

__all__ = ['BPBrowser', 'BProBrowser']


class BPBrowser(LoginBrowser, StatesMixin):
    BASEURL = 'https://voscomptesenligne.labanquepostale.fr'
    STATE_DURATION = 10

    # FIXME beware that '.*' in start of URL() won't match all domains but only under BASEURL

    login_image = URL(r'.*wsost/OstBrokerWeb/loginform\?imgid=', UselessPage)
    login_page = URL(r'.*wsost/OstBrokerWeb/loginform.*', LoginPage)
    repositionner_chemin_courant = URL(r'.*authentification/repositionnerCheminCourant-identif.ea', repositionnerCheminCourant)
    init_ident = URL(r'.*authentification/initialiser-identif.ea', Initident)
    check_password = URL(r'.*authentification/verifierMotDePasse-identif.ea',
                         r'/securite/authentification/verifierPresenceCompteOK-identif.ea',
                         r'.*//voscomptes/identification/motdepasse.jsp',
                         CheckPassword)

    redirect_page = URL(r'.*voscomptes/identification/identification.ea.*',
                        r'.*voscomptes/synthese/3-synthese.ea',
                        RedirectPage)

    auth_page = URL(r'voscomptes/canalXHTML/securite/gestionAuthentificationForte/init-gestionAuthentificationForte.ea', TwoFAPage)
    validated_2fa_page = URL(r'voscomptes/canalXHTML/securite/gestionAuthentificationForte/../../securite/authentification/retourDSP2-identif.ea',
                             r'voscomptes/canalXHTML/securite/authentification/retourDSP2-identif.ea',
                             Validated2FAPage)
    decoupled_page = URL(r'/voscomptes/canalXHTML/securite/gestionAuthentificationForte/validationTerminal-gestionAuthentificationForte.ea', DecoupledPage)
    sms_page = URL(r'/voscomptes/canalXHTML/securite/gestionAuthentificationForte/authenticateCerticode-gestionAuthentificationForte.ea', SmsPage)
    sms_validation = URL(r'/voscomptes/canalXHTML/securite/gestionAuthentificationForte/validation-gestionAuthentificationForte.ea', SmsPage)

    par_accounts_checking = URL('/voscomptes/canalXHTML/comptesCommun/synthese_ccp/afficheSyntheseCCP-synthese_ccp.ea', AccountList)
    par_accounts_savings_and_invests = URL('/voscomptes/canalXHTML/comptesCommun/synthese_ep/afficheSyntheseEP-synthese_ep.ea', AccountList)
    par_accounts_loan = URL('/voscomptes/canalXHTML/pret/encours/consulterPrets-encoursPrets.ea',
                            '/voscomptes/canalXHTML/pret/encours/detaillerPretPartenaireListe-encoursPrets.ea',
                            '/voscomptes/canalXHTML/pret/encours/detaillerOffrePretImmoListe-encoursPrets.ea',
                            '/voscomptes/canalXHTML/pret/encours/detaillerOffrePretConsoListe-encoursPrets.ea',
                            '/voscomptes/canalXHTML/pret/creditRenouvelable/init-consulterCreditRenouvelable.ea',
                            '/voscomptes/canalXHTML/pret/encours/rechercherPret-encoursPrets.ea',
                            '/voscomptes/canalXHTML/sso/commun/init-integration.ea\?partenaire=cristalCEC',
                            AccountList)

    revolving_start = URL(r'/voscomptes/canalXHTML/sso/lbpf/souscriptionCristalFormAutoPost.jsp', AccountList)
    par_accounts_revolving = URL(r'https://espaceclientcreditconso.labanquepostale.fr/sav/loginlbpcrypt.do', RevolvingAttributesPage)


    accounts_rib = URL(r'.*voscomptes/canalXHTML/comptesCommun/imprimerRIB/init-imprimer_rib.ea.*',
                       '/voscomptes/canalXHTML/comptesCommun/imprimerRIB/init-selection_rib.ea', AccountRIB)

    saving_summary = URL(r'/voscomptes/canalXHTML/assurance/vie/reafficher-assuranceVie.ea(\?numContrat=(?P<id>\w+))?',
                         r'/voscomptes/canalXHTML/assurance/retraiteUCEuro/afficher-assuranceRetraiteUCEuros.ea(\?numContrat=(?P<id>\w+))?',
                         r'/voscomptes/canalXHTML/assurance/retraitePoints/reafficher-assuranceRetraitePoints.ea(\?numContrat=(?P<id>\w+))?',
                         r'/voscomptes/canalXHTML/assurance/prevoyance/reafficher-assurancePrevoyance.ea(\?numContrat=(?P<id>\w+))?',
                         SavingAccountSummary)

    lifeinsurance_invest = URL(r'/voscomptes/canalXHTML/assurance/retraiteUCEuro/afficherSansDevis-assuranceRetraiteUCEuros.ea\?numContrat=(?P<id>\w+)',
                               LifeInsuranceInvest)
    lifeinsurance_invest2 = URL(r'/voscomptes/canalXHTML/assurance/vie/valorisation-assuranceVie.ea\?numContrat=(?P<id>\w+)', LifeInsuranceInvest)
    lifeinsurance_history = URL(r'/voscomptes/canalXHTML/assurance/vie/historiqueVie-assuranceVie.ea\?numContrat=(?P<id>\w+)', LifeInsuranceHistory)
    lifeinsurance_hist_inv = URL(r'/voscomptes/canalXHTML/assurance/vie/detailMouvement-assuranceVie.ea\?idMouvement=(?P<id>\w+)',
                                 r'/voscomptes/canalXHTML/assurance/vie/detailMouvementHermesBompard-assuranceVie.ea\?idMouvement=(\w+)', LifeInsuranceHistoryInv)
    lifeinsurance_cachemire_catalog = URL(r'https://www.labanquepostale.fr/particuliers/bel_particuliers/assurance/accueil_cachemire.html', CachemireCatalogPage)

    market_home = URL(r'https://labanquepostale.offrebourse.com/fr/\d+/?', MarketHomePage)
    market_login = URL(r'/voscomptes/canalXHTML/bourse/aiguillage/oicFormAutoPost.jsp', MarketLoginPage)
    market_check = URL(r'/voscomptes/canalXHTML/bourse/aiguillage/lancerBourseEnLigne-connexionBourseEnLigne.ea', MarketCheckPage)
    useless = URL(r'https://labanquepostale.offrebourse.com/ReroutageSJR', UselessPage)

    retirement_hist = URL(r'/voscomptes/canalXHTML/assurance/retraitePoints/historiqueRetraitePoint-assuranceRetraitePoints.ea(\?numContrat=(?P<id>\w+))?',
                          r'/voscomptes/canalXHTML/assurance/retraiteUCEuro/historiqueMouvements-assuranceRetraiteUCEuros.ea(\?numContrat=(?P<id>\w+))?',
                          r'/voscomptes/canalXHTML/assurance/prevoyance/consulterHistorique-assurancePrevoyance.ea(\?numContrat=(?P<id>\w+))?',
                          RetirementHistory)

    par_account_checking_history = URL('/voscomptes/canalXHTML/CCP/releves_ccp/init-releve_ccp.ea\?typeRecherche=10&compte.numero=(?P<accountId>.*)',
                                       '/voscomptes/canalXHTML/CCP/releves_ccp/afficher-releve_ccp.ea', AccountHistory)
    single_card_history = URL(r'/voscomptes/canalXHTML/CB/releveCB/preparerRecherche-mouvementsCarteDD.ea\?typeListe=(?P<monthIndex>\d+)', AccountHistory)
    deferred_card_history = URL(r'/voscomptes/canalXHTML/CB/releveCB/init-mouvementsCarteDD.ea\?compte.numero=(?P<accountId>\w+)&indexCompte=(?P<cardIndex>\d+)&typeListe=(?P<monthIndex>\d+)', AccountHistory)
    deferred_card_history_multi = URL(r'/voscomptes/canalXHTML/CB/releveCB/preparerRecherche-mouvementsCarteDD.ea\?indexCompte=(?P<accountId>\w+)&indexCarte=(?P<cardIndex>\d+)&typeListe=(?P<monthIndex>\d+)',
                                      r'/voscomptes/canalXHTML/CB/releveCB/preparerRecherche-mouvementsCarteDD.ea\?compte.numero=(?P<accountId>\w+)&indexCarte=(?P<cardIndex>\d+)&typeListe=(?P<monthIndex>\d+)', AccountHistory)
    par_account_checking_coming = URL('/voscomptes/canalXHTML/CCP/releves_ccp_encours/preparerRecherche-releve_ccp_encours.ea\?compte.numero=(?P<accountId>.*)&typeRecherche=1',
                                      '/voscomptes/canalXHTML/CB/releveCB/init-mouvementsCarteDD.ea\?compte.numero=(?P<accountId>.*)&typeListe=1&typeRecherche=10',
                                      '/voscomptes/canalXHTML/CCP/releves_ccp_encours/preparerRecherche-releve_ccp_encours.ea\?indexCompte',
                                      '/voscomptes/canalXHTML/CNE/releveCNE_encours/init-releve_cne_en_cours.ea\?compte.numero',
                                      '/voscomptes/canalXHTML/CNE/releveCNE_encours/init-releve_cne_en_cours.ea\?indexCompte=(?P<accountId>.*)&typeRecherche=1&typeMouvements=CNE', AccountHistory)
    par_account_savings_and_invests_history = URL('/voscomptes/canalXHTML/CNE/releveCNE/init-releve_cne.ea\?typeRecherche=10&compte.numero=(?P<accountId>.*)',
                                                  '/voscomptes/canalXHTML/CNE/releveCNE/releveCNE-releve_cne.ea',
                                                  '/voscomptes/canalXHTML/CNE/releveCNE/frame-releve_cne.ea\?compte.numero=.*&typeRecherche=.*',
                                                  AccountHistory)

    cards_list = URL('/voscomptes/canalXHTML/CB/releveCB/init-mouvementsCarteDD.ea\?compte.numero=(?P<account_id>\w+)$',
                     r'.*CB/releveCB/init-mouvementsCarteDD.ea.*',
                     CardsList)

    transfer_choose = URL(r'/voscomptes/canalXHTML/virement/mpiaiguillage/init-saisieComptes.ea', TransferChooseAccounts)
    transfer_complete = URL(r'/voscomptes/canalXHTML/virement/mpiaiguillage/soumissionChoixComptes-saisieComptes.ea',
                            r'/voscomptes/canalXHTML/virement/virementSafran_national/init-creerVirementNational.ea',
                            # The two following urls are obtained after a redirection made after a form
                            # No parameters or data seem to change that the website go back to the evious folder, using ".."
                            # We can't do much since it is finaly handled by the module requests
                            r'/voscomptes/canalXHTML/virement/mpiaiguillage/\.\./virementSafran_national/init-creerVirementNational.ea',
                            r'/voscomptes/canalXHTML/virement/mpiaiguillage/\.\./virementSafran_sepa/init-creerVirementSepa.ea',
                            r'/voscomptes/canalXHTML/virement/virementSafran_sepa/init-creerVirementSepa.ea',
                            CompleteTransfer)
    transfer_confirm = URL(r'/voscomptes/canalXHTML/virement/virementSafran_pea/validerVirementPea-virementPea.ea',
                           r'/voscomptes/canalXHTML/virement/virementSafran_sepa/valider-creerVirementSepa.ea',
                           r'/voscomptes/canalXHTML/virement/virementSafran_sepa/valider-virementSepa.ea',
                           r'/voscomptes/canalXHTML/virement/virementSafran_sepa/confirmerInformations-virementSepa.ea',
                           r'/voscomptes/canalXHTML/virement/virementSafran_national/valider-creerVirementNational.ea',
                           r'/voscomptes/canalXHTML/virement/virementSafran_national/validerVirementNational-virementNational.ea',
                           # the following url is already used in transfer_summary
                           # but we need it to detect the case where the website displaies the list of devices
                           # when a transfer is made with an otp or decoupled
                           r'/voscomptes/canalXHTML/virement/virementSafran_sepa/confirmer-creerVirementSepa.ea', TransferConfirm)
    transfer_summary = URL(r'/voscomptes/canalXHTML/virement/virementSafran_national/confirmerVirementNational-virementNational.ea',
                           r'/voscomptes/canalXHTML/virement/virementSafran_pea/confirmerInformations-virementPea.ea',
                           r'/voscomptes/canalXHTML/virement/virementSafran_sepa/confirmer-creerVirementSepa.ea',
                           r'/voscomptes/canalXHTML/virement/virementSafran_national/confirmer-creerVirementNational.ea',
                           r'/voscomptes/canalXHTML/virement/virementSafran_sepa/confirmerInformations-virementSepa.ea', TransferSummary)

    create_recipient = URL(r'/voscomptes/canalXHTML/virement/mpiGestionBeneficiairesVirementsCreationBeneficiaire/init-creationBeneficiaire.ea',
                           r'/voscomptes/canalXHTML/virement/virementSafran_commun/.*.ea',
                            CreateRecipient)
    validate_country = URL(r'/voscomptes/canalXHTML/virement/mpiGestionBeneficiairesVirementsCreationBeneficiaire/validationSaisiePaysBeneficiaire-creationBeneficiaire.ea',
                             ValidateCountry)
    validate2_recipient = URL(r'/voscomptes/canalXHTML/virement/mpiGestionBeneficiairesVirementsCreationBeneficiaire/valider-creationBeneficiaire.ea', ValidateRecipient)
    rcpt_code = URL(r'/voscomptes/canalXHTML/virement/mpiGestionBeneficiairesVirementsCreationBeneficiaire/validerRecapBeneficiaire-creationBeneficiaire.ea', ConfirmPage)
    rcpt_summary = URL(r'/voscomptes/canalXHTML/virement/mpiGestionBeneficiairesVirementsCreationBeneficiaire/finalisation-creationBeneficiaire.ea', RcptSummary)

    badlogin = URL(r'https://transverse.labanquepostale.fr/.*ost/messages\.CVS\.html\?param=0x132120c8.*', # still valid?
                   r'https://transverse.labanquepostale.fr/xo_/messages/message.html\?param=0x132120c8.*',
                   BadLoginPage)
    disabled_account = URL(r'.*ost/messages\.CVS\.html\?param=0x132120cb.*',
                           r'.*/message\.html\?param=0x132120c.*',
                           r'https://transverse.labanquepostale.fr/xo_/messages/message.html\?param=0x132120cb.*',
                           AccountDesactivate)

    unavailable = URL(r'https?://.*.labanquepostale.fr/delestage.html',
                      r'https://transverse.labanquepostale.fr/xo_/messages/message.html\?param=delestage',
                      UnavailablePage)
    rib_dl = URL(r'.*/voscomptes/rib/init-rib.ea', DownloadRib)
    rib = URL(r'.*/voscomptes/rib/preparerRIB-rib.*', RibPage)
    advisor = URL(r'/ws_q45/Q45/canalXHTML/commun/authentification/init-identif.ea\?origin=particuliers&codeMedia=0004&entree=HubHome',
                  r'/ws_q45/Q45/canalXHTML/desktop/home/init-home.ea', Advisor)

    login_url = 'https://voscomptesenligne.labanquepostale.fr/wsost/OstBrokerWeb/loginform?TAM_OP=login&' \
            'ERROR_CODE=0x00000000&URL=%2Fvoscomptes%2FcanalXHTML%2Fidentif.ea%3Forigin%3Dparticuliers'

    pre_mandate = URL(r'/voscomptes/canalXHTML/sso/commun/init-integration.ea\?partenaire=procapital', PreMandate)
    pre_mandate_bis = URL(r'https://www.gestion-sous-mandat.labanquepostale-gestionprivee.fr/lbpgp/secure/main.html', PreMandateBis)
    mandate_accounts_list = URL(r'https://www.gestion-sous-mandat.labanquepostale-gestionprivee.fr/lbpgp/secure/accounts_list.html', MandateAccountsList)
    mandate_market = URL(r'https://www.gestion-sous-mandat.labanquepostale-gestionprivee.fr/lbpgp/secure_account/selectedAccountDetail.html', MandateMarket)
    mandate_life = URL(r'https://www.gestion-sous-mandat.labanquepostale-gestionprivee.fr/lbpgp/secure_main/asvContratClient.html',
                       r'https://www.gestion-sous-mandat.labanquepostale-gestionprivee.fr/lbpgp/secure_ajax/asvSupportsDetail.html', MandateLife)

    profile = URL('/voscomptes/canalXHTML/donneesPersonnelles/consultationDonneesPersonnellesSB490A/init-consulterDonneesPersonnelles.ea', ProfilePage)

    subscription = URL('/voscomptes/canalXHTML/relevePdf/relevePdf_historique/reinitialiser-historiqueRelevesPDF.ea', SubscriptionPage)
    subscription_search = URL('/voscomptes/canalXHTML/relevePdf/relevePdf_historique/form-historiqueRelevesPDF\.ea', SubscriptionPage)
    download_page = URL(r'/voscomptes/canalXHTML/relevePdf/relevePdf_historique/telechargerPDF-historiqueRelevesPDF.ea\?ts=.*&listeRecherche=.*', DownloadPage)

    accounts = None

    def __init__(self, config, *args, **kwargs):
        self.weboob = kwargs.pop('weboob')
        self.config = config
        super(BPBrowser, self).__init__(*args, **kwargs)
        self.resume = config['resume'].get()
        self.request_information = config['request_information'].get()
        self.__states__ += ('sms_form', )

        dirname = self.responses_dirname
        if dirname:
            dirname += '/bourse'
        self.linebourse = LinebourseBrowser('https://labanquepostale.offrebourse.com/', logger=self.logger, responses_dirname=dirname, weboob=self.weboob, proxy=self.PROXIES)
        self.recipient_form = None

    def load_state(self, state):
        if state.get('url'):
            # We don't want to come back to last URL during SCA
            state.pop('url')
        super(BPBrowser, self).load_state(state)

        if 'recipient_form' in state and state['recipient_form'] is not None:
            self.logged = True

    def deinit(self):
        super(BPBrowser, self).deinit()
        self.linebourse.deinit()

    def open(self, *args, **kwargs):
        try:
            return super(BPBrowser, self).open(*args, **kwargs)
        except ServerError as err:
            if "/../" not in err.response.url:
                raise
            # this shit website includes ".." in an absolute url in the Location header
            # requests passes it verbatim, and the site can't handle it
            self.logger.debug('site has "/../" in their url, fixing url manually')
            parts = list(urlsplit(err.response.url))
            parts[2] = os.path.abspath(parts[2])
            return self.open(urlunsplit(parts))

    def login_without_2fa(self):
        self.location(self.login_url)
        self.page.login(self.username, self.password)

        if self.redirect_page.is_here():
            if self.page.check_for_perso():
                raise BrowserIncorrectPassword("L'identifiant utilisé est celui d'un compte de Particuliers.")
            error = self.page.get_error()
            raise BrowserUnavailable(error or '')

        if self.badlogin.is_here():
            raise BrowserIncorrectPassword()
        if self.disabled_account.is_here():
            raise BrowserBanned()

    def do_login(self):
        self.code = self.config['code'].get()
        if self.resume:
            return self.handle_polling()
        elif self.code:
            return self.handle_sms()

        self.login_without_2fa()

        self.auth_page.go()
        if self.auth_page.is_here():
            # Handle 2FA
            # 2FA seem to be handled by LBP. Indeed logins after 2FA will redirect to the LBP main page
            # Consequently no state for future connexion needs to be kept
            if self.request_information is None:
                raise NeedInteractiveFor2FA()
            auth_method = self.page.get_auth_method()

            if auth_method == 'cer+':
                # We force here the first device present
                self.decoupled_page.go(params={'deviceSelected': '0'})
                raise AppValidation(self.page.get_decoupled_message())

            elif auth_method == 'cer':
                self.location('/voscomptes/canalXHTML/securite/gestionAuthentificationForte/authenticateCerticode-gestionAuthentificationForte.ea')
                self.page.check_if_is_blocked()
                self.sms_form = self.page.get_sms_form()
                raise BrowserQuestion(Value('code', label='Entrez le code reçu par SMS'))

            elif auth_method == 'no2fa':
                self.location(self.page.get_skip_url())

        # If we are here, we don't need 2FA, we are logged

    def handle_polling(self):
        timeout = time.time() + 300.00
        while time.time() < timeout:
            polling = self.location('/voscomptes/canalXHTML/securite/gestionAuthentificationForte/validationOperation-gestionAuthentificationForte.ea').json()
            result = polling['statutOperation']
            if result == '1':
                # Waiting for PSU validation
                time.sleep(10)
                continue
            elif result == '2':
                # Validated
                break
            elif result == '3':
                raise AppValidationCancelled()
            elif result == '6':
                raise AppValidationExpired()
            else:
                assert False, 'statutOperation: %s is not handled' % result

            raise AppValidationExpired()

        self.location('/voscomptes/canalXHTML/securite/gestionAuthentificationForte/finalisation-gestionAuthentificationForte.ea')

    def handle_sms(self):
        self.sms_form['codeOTPSaisi'] = self.code
        self.sms_validation.go(data=self.sms_form)
        if not self.validated_2fa_page.is_here() and self.page.is_sms_wrong():
            raise BrowserIncorrectPassword('Le code de sécurité que vous avez saisi est erroné.')

    @need_login
    def get_accounts_list(self):
        if self.session.cookies.get('indicateur'):
            # Malformed cookie to delete to reach other spaces
            del self.session.cookies['indicateur']

        if self.accounts is None:
            accounts = []
            to_check = []

            owner_name = self.get_profile().name
            self.par_accounts_checking.go()

            pages = [self.par_accounts_checking, self.par_accounts_savings_and_invests, self.par_accounts_loan]
            no_accounts = 0
            for page in pages:
                page.go()

                assert page.is_here(), "AccountList type page not reached"
                if self.page.no_accounts:
                    no_accounts += 1
                    continue

                for account in self.page.iter_accounts(name=owner_name):
                    if account.type == Account.TYPE_LOAN:
                        self.location(account.url)
                        if 'initSSO' not in account.url:
                            for loan in self.page.iter_loans():
                                loan.currency = account.currency
                                accounts.append(loan)
                            student_loan = self.page.get_student_loan()
                            if student_loan:
                                # Number of headers and item elements are the same
                                assert len(student_loan._heads) == len(student_loan._items)
                                student_loan.currency = account.currency
                                accounts.append(student_loan)
                        else:
                            # The main revolving page is not accessible, we can reach it by this new way
                            self.go_revolving()
                            revolving_loan = self.page.get_revolving_attributes(account)
                            accounts.append(revolving_loan)
                        page.go()

                    elif account.type == Account.TYPE_PERP:
                        # PERP balances must be fetched from the details page,
                        # otherwise we just scrape the "Rente annuelle estimée":
                        balance = self.open(account.url).page.get_balance()
                        if balance is not None:
                            account.balance = balance
                        accounts.append(account)

                    else:
                        accounts.append(account)
                        if account.type == Account.TYPE_CHECKING and account._has_cards:
                            to_check.append(account)

                if self.page.has_mandate_management_space:
                    self.location(self.page.mandate_management_space_link())
                    for mandate_account in self.page.iter_accounts():
                        accounts.append(mandate_account)

                for account in to_check:
                    accounts.extend(self.iter_cards(account))
                to_check = []

            self.accounts = accounts

            # if we are sure there is no accounts on the all visited pages,
            # it is legit.
            if no_accounts == len(pages):
                raise NoAccountsException()

        return self.accounts

    @retry(BrowserUnavailable, delay=5)
    def go_revolving(self):
        self.revolving_start.go()
        self.page.go_revolving()

    def iter_cards(self, account):
        self.deferred_card_history.go(accountId=account.id, monthIndex=0, cardIndex=0)
        if self.cards_list.is_here():
            self.logger.debug('multiple cards for account %r', account)
            for card in self.page.get_cards(parent_id=account.id):
                card.parent = account
                yield card
        else:
            # The website does not shows the transactions if we do not
            # redirect to a precedent month with weboob then come back
            self.single_card_history.go(monthIndex=1)
            self.single_card_history.go(monthIndex=0)
            self.logger.debug('single card for account %r', account)
            self.logger.debug('parsing %r', self.url)
            card = self.page.get_single_card(parent_id=account.id)
            card.parent = account
            yield card

    @need_login
    def get_history(self, account):
        if account.type == Account.TYPE_CHECKING and account.balance == 0:
            # When the balance is 0, we get a website unavailable on the history page
            # and the following navigation is broken
            return []
        # TODO scrap pdf to get history of mandate accounts
        if 'gestion-sous-mandat' in account.url:
            return []

        if account.type in (account.TYPE_PEA, account.TYPE_MARKET):
            self.go_linebourse(account)
            return self.linebourse.iter_history(account.id)

        if account.type in (Account.TYPE_LOAN, Account.TYPE_REVOLVING_CREDIT):
            return []

        if account.type == Account.TYPE_CARD:
            return (tr for tr in self.iter_card_transactions(account) if not tr._coming)
        else:
            self.location(account.url)

            history = {Account.TYPE_CHECKING: self.par_account_checking_history,
                       Account.TYPE_SAVINGS: self.par_account_savings_and_invests_history,
                       Account.TYPE_MARKET: self.par_account_savings_and_invests_history
                      }.get(account.type)

            if history is not None and account.label != 'COMPTE ATTENTE':
                history.go(accountId=account.id)

            # TODO be smarter by avoid fetching all, sorting all and returning all if only coming were desired
            if hasattr(self.page, 'iter_transactions') and self.page.has_transactions():
                return self.page.iter_transactions()

            elif account.type in (Account.TYPE_PERP, Account.TYPE_LIFE_INSURANCE) and self.retirement_hist.is_here():
                return self.page.get_history()

            return []


    @need_login
    def go_linebourse(self, account):
        # Sometimes the redirection done from MarketLoginPage
        # (to https://labanquepostale.offrebourse.com/ReroutageSJR)
        # throws an error 404 or 403
        location = retry(HTTPError, delay=5)(self.location)
        location(account.url)

        # TODO Might be deprecated, check the logs after some time to
        # check if this is still used.
        if not self.market_home.is_here():
            self.logger.debug('Landed in unexpected market page, doing self.market_login.go()')
            go = retry(HTTPError, delay=5)(self.market_login.go)
            go()

        self.linebourse.session.cookies.update(self.session.cookies)
        self.par_accounts_checking.go()

    def _get_coming_transactions(self, account):
        if account.type == Account.TYPE_CHECKING:
            self.location(account.url)
            self.par_account_checking_coming.go(accountId=account.id)

            if self.par_account_checking_coming.is_here() and self.page.has_transactions():
                for tr in self.page.iter_transactions(coming=True):
                    yield tr

    @need_login
    def get_coming(self, account):
        if 'gestion-sous-mandat' in account.url:
            return []
        # When the balance is 0, we get a website unavailable on the history page
        # and the following navigation is broken
        if account.type == Account.TYPE_CHECKING and account.balance != 0:
            return self._get_coming_transactions(account)
        elif account.type == Account.TYPE_CARD:
            transactions = []
            for tr in self.iter_card_transactions(account):
                if tr._coming:
                    transactions.append(tr)
            return transactions

        return []

    @need_login
    def iter_card_transactions(self, account):
        def iter_transactions(link, urlobj):
            # we go back to main menue otherwise we get an error 500.
            self.cards_list.go(account_id=account.parent.id)
            self.location(link)
            assert urlobj.is_here()
            ncard = self.page.params.get('cardIndex', 0)
            self.logger.debug('handling card %s for account %r', ncard, account)
            urlobj.go(accountId=account.parent.id, monthIndex=1, cardIndex=ncard)

            for t in range(6):
                try:
                    urlobj.go(accountId=account.parent.id, monthIndex=t, cardIndex=ncard)
                except BrowserUnavailable:
                    self.logger.debug("deferred card history stop at %s", t)
                    break

                if urlobj.is_here():
                    for tr in self.page.get_history(deferred=True):
                        yield tr

        assert account.type == Account.TYPE_CARD
        for tr in iter_transactions(account.url, self.deferred_card_history_multi):
            yield tr

    @need_login
    def iter_investment(self, account):
        if 'gestion-sous-mandat' in account.url:
            return self.location(account.url).page.iter_investments()

        if account.type in (account.TYPE_PEA, account.TYPE_MARKET):
            self.go_linebourse(account)
            investments = list(self.linebourse.iter_investment(account.id))
            liquidity = self.linebourse.get_liquidity(account.id)
            if liquidity:
                # avoid to append None
                investments.append(liquidity)
            return investments

        if account.type != Account.TYPE_LIFE_INSURANCE:
            return iter([])

        investments = []

        self.lifeinsurance_invest.go(id=account.id)
        assert self.lifeinsurance_invest.is_here()
        if not self.page.has_error():
            investments = list(self.page.iter_investments())

        if not investments:
            self.lifeinsurance_invest2.go(id=account.id)
            investments = list(self.page.iter_investments())

        if self.page.get_cachemire_link():
            # fetch ISIN codes for cachemire invests
            self.lifeinsurance_cachemire_catalog.go()
            product_codes = self.page.product_codes
            for inv in investments:
                inv.code = product_codes.get(inv.label.upper(), NotAvailable)

        return investments

    @need_login
    def iter_recipients(self, account_id):
        return self.transfer_choose.stay_or_go().iter_recipients(account_id=account_id)

    @need_login
    def init_transfer(self, account, recipient, amount, transfer):
        self.transfer_choose.stay_or_go()
        self.page.init_transfer(account.id, recipient._value, amount)

        assert self.transfer_complete.is_here(), 'An error occured while validating the first part of the transfer.'
        self.page.complete_transfer(transfer)

        return self.page.handle_response(account, recipient, amount, transfer.label)

    @need_login
    def execute_transfer(self, transfer, code=None):
        assert self.transfer_confirm.is_here(), 'Case not handled.'
        self.page.confirm()
        # Should only happen if double auth.
        if self.transfer_confirm.is_here():
            self.page.choose_device()
            self.page.double_auth(transfer)
        return self.page.handle_response(transfer)

    def build_recipient(self, recipient):
        r = Recipient()
        r.iban = recipient.iban
        r.id = recipient.iban
        r.label = recipient.label
        r.category = recipient.category
        r.enabled_at = datetime.now().replace(microsecond=0) + timedelta(days=5)
        r.currency = u'EUR'
        r.bank_name = recipient.bank_name
        return r

    def post_code(self, code):
        data = {}
        for k, v in self.recipient_form.items():
            if k != 'url':
                data[k] = v
        data['codeOTPSaisi'] = code
        self.location(self.recipient_form['url'], data=data)

    @need_login
    def new_recipient(self, recipient, is_bp_account=False, **kwargs):
        if 'code' in kwargs:
            assert self.rcpt_code.is_here()

            self.post_code(kwargs['code'])
            self.recipient_form = None
            assert self.rcpt_summary.is_here()
            return self.build_recipient(recipient)

        self.create_recipient.go().choose_country(recipient, is_bp_account)
        self.page.populate(recipient)
        if self.page.is_bp_account():
            return self.new_recipient(recipient, is_bp_account=True, **kwargs)

        # send sms
        self.location(self.page.get_confirm_link())
        self.page.set_browser_form()
        raise AddRecipientStep(self.build_recipient(recipient), Value('code', label='Veuillez saisir votre code de validation'))

    @need_login
    def get_advisor(self):
        return iter([self.advisor.go().get_advisor()])

    @need_login
    def get_profile(self):
        return self.profile.go().get_profile()

    @need_login
    def iter_subscriptions(self):
        subscriber = self.get_profile().name
        self.subscription.go()
        return self.page.iter_subscriptions(subscriber=subscriber)

    @need_login
    def iter_documents(self, subscription):
        self.subscription.go()
        params = self.page.get_params(subscription._full_id)

        for year in self.page.get_years():
            params['formulaire.anneeRecherche'] = year

            if any(l in subscription.label for l in ('PEA', 'TIT')):
                for statement_type in self.page.STATEMENT_TYPES:
                    params['formulaire.typeReleve'] = statement_type
                    self.subscription_search.go(params=params)

                    if self.page.has_error():
                        # you may have an error message
                        # instead of telling you that there are no statement for a year
                        continue

                    for doc in self.page.iter_documents(sub_id=subscription.id):
                        yield doc
            else:
                self.subscription_search.go(params=params)
                for doc in self.page.iter_documents(sub_id=subscription.id):
                    yield doc

    @need_login
    def download_document(self, document):
        download_page = self.open(document.url).page
        # may have an iframe
        return download_page.get_content()


class BProBrowser(BPBrowser):
    login_url = "https://banqueenligne.entreprises.labanquepostale.fr/wsost/OstBrokerWeb/loginform?TAM_OP=login&ERROR_CODE=0x00000000&URL=%2Fws_q47%2Fvoscomptes%2Fidentification%2Fidentification.ea%3Forigin%3Dprofessionnels"
    accounts_and_loans_url = None

    pro_accounts_list = URL(r'.*voscomptes/synthese/synthese.ea', ProAccountsList)

    pro_history = URL(r'.*voscomptes/historique(ccp|cne)/(\d+-)?historique(operationnel)?(ccp|cne).*', ProAccountHistory)

    useless2 = URL(r'.*/voscomptes/bourseenligne/lancementBourseEnLigne-bourseenligne.ea\?numCompte=(?P<account>\d+)', UselessPage)
    market_login = URL(r'.*/voscomptes/bourseenligne/oicformautopost.jsp', MarketLoginPage)

    subscription = URL(r'(?P<base_url>.*)/voscomptes/relevespdf/histo-consultationReleveCompte.ea',
                       r'.*/voscomptes/relevespdf/rechercheHistoRelevesCompte-consultationReleveCompte.ea', ProSubscriptionPage)
    download_page = URL(r'.*/voscomptes/relevespdf/telechargerReleveCompteSelectionne-consultationReleveCompte.ea\?idReleveSelectionne=.*', DownloadPage)

    BASEURL = 'https://banqueenligne.entreprises.labanquepostale.fr'

    def set_variables(self):
        v = urlsplit(self.url)
        version = v.path.split('/')[1]

        self.base_url = 'https://banqueenligne.entreprises.labanquepostale.fr/%s' % version
        self.accounts_url = self.base_url + '/voscomptes/synthese/synthese.ea'

    def go_linebourse(self, account):
        self.location(account.url)
        self.location('../bourseenligne/oicformautopost.jsp')
        self.linebourse.session.cookies.update(self.session.cookies)
        self.location(self.accounts_url)

    @need_login
    def get_history(self, account):
        if account.type in (account.TYPE_PEA, account.TYPE_MARKET):
            self.go_linebourse(account)
            return self.linebourse.iter_history(account.id)

        transactions = []
        v = urlsplit(account.url)
        args = dict(parse_qsl(v.query))
        args['typeRecherche'] = 10

        self.location(v.path, params=args)

        self.first_transactions = []
        for tr in self.page.iter_history():
            transactions.append(tr)
        transactions.sort(key=lambda tr: tr.rdate, reverse=True)

        return transactions

    def _get_coming_transactions(self, account):
        return []

    def check_accounts_list_error(self):
        error = self.page.get_errors()
        if error:
            if 'veuillez-vous rapprocher du mandataire principal de votre contrat' in error.lower():
                raise ActionNeeded(error)
            raise BrowserUnavailable(error)

    @need_login
    def get_accounts_list(self):
        if self.accounts is None:
            self.set_variables()

            accounts = []
            ids = set()

            self.location(self.accounts_url)
            assert self.pro_accounts_list.is_here()

            self.check_accounts_list_error()
            for account in self.page.iter_accounts():
                ids.add(account.id)
                accounts.append(account)

            if self.accounts_and_loans_url:
                self.location(self.accounts_and_loans_url)
                assert self.pro_accounts_list.is_here()

            self.check_accounts_list_error()
            for account in self.page.iter_accounts():
                if account.id not in ids:
                    ids.add(account.id)
                    accounts.append(account)

            for acc in accounts:
                self.location('%s/voscomptes/rib/init-rib.ea' % self.base_url)
                value = self.page.get_rib_value(acc.id)
                if value:
                    self.location('%s/voscomptes/rib/preparerRIB-rib.ea?idxSelection=%s' % (self.base_url, value))
                    if self.rib.is_here():
                        acc.iban = self.page.get_iban()

            self.accounts = accounts

        return self.accounts

    @need_login
    def get_profile(self):
        acc = self.get_accounts_list()[0]
        self.location('%s/voscomptes/rib/init-rib.ea' % self.base_url)
        value = self.page.get_rib_value(acc.id)
        if value:
            self.location('%s/voscomptes/rib/preparerRIB-rib.ea?idxSelection=%s' % (self.base_url, value))
            if self.rib.is_here():
                return self.page.get_profile()

    @need_login
    def iter_subscriptions(self):
        subscriber = self.get_profile().name
        self.subscription.go(base_url=self.base_url)
        return self.page.iter_subscriptions(subscriber=subscriber)

    @need_login
    def iter_documents(self, subscription):
        self.subscription.go(base_url=self.base_url)

        for year in self.page.get_years():
            self.page.submit_form(sub_number=subscription._number, year=year)

            if self.page.no_statement():
                self.subscription.go(base_url=self.base_url)
                continue

            for doc in self.page.iter_documents(sub_id=subscription.id):
                yield doc

            self.subscription.go(base_url=self.base_url)

    @need_login
    def download_document(self, document):
        # must be sure to be on the right page before downloading
        if self.subscription.is_here() and self.page.has_document(document.date):
            return self.open(document.url).content

        self.subscription.go(base_url=self.base_url)
        sub_number = self.page.get_sub_number(document.id)
        year = str(document.date.year)
        self.page.submit_form(sub_number=sub_number, year=year)

        return self.open(document.url).content
