################################################################################
# REST API client script for batch access to Copernicus Land Monitoring Service 
# data on WEkEO.
################################################################################
#
# Publication date XXXXXXXX
# License: CC-BY (not decided yet)
# Script Version 1.0
# Contact: copernicus@eea.europa.eu
# 
# Requirements: Python Version 2/3??
# Packages: see imports below
#
################################################################################
#
# This Python script allows you to do REST queries to the Copernicus Land 
# Monitoring Service (CLMS) HTTP API. 
# It forsees capabilities for search and download CLMS products (currently only 
# the Sentinel 2 based prducts of HR-S&I). Users are recommended to rely on this 
# python script, to perform custom and automatic queries.
# Users should notice that using the interactive web interface also generates the
# corresponding REST query, that can be ingested directly by this script.
#
################################################################################
# Legal notice about Copernicus data: 
#
# Access to data is based on a principle of full, open and free access as 
# established by the Copernicus data and information policy Regulation (EU) 
# No 1159/2013 of 12 July 2013. This regulation establishes registration and 
# licensing conditions for GMES/Copernicus users and can be found here: 
# http://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32013R1159.  
# 
# Free, full and open access to this data set is made on the conditions that:
# 
# 1. When distributing or communicating Copernicus dedicated data and Copernicus
#    service information to the public, users shall inform the public of the 
#    source of that data and information.
# 2. Users shall make sure not to convey the impression to the public that the 
#    user's activities are officially endorsed by the Union.
# 3. Where that data or information has been adapted or modified, the user shall
#    clearly state this.
# 4. The data remain the sole property of the European Union. Any information and
#    data produced in the framework of the action shall be the sole property of 
#    the European Union. Any communication and publication by the beneficiary 
#    shall acknowledge that the data were produced "with funding by the European
#    Union".
#
################################################################################

import os
import re
import sys
import json
import time
import logging
import datetime
import argparse
import subprocess
from functools import partial
import requests

def validate_Rfc3339(date_text):
    try:
        datetime.datetime.strptime(date_text, '%Y-%m-%dT%H:%M:%SZ')
        return date_text
    except:
        raise ValueError("Incorrect date format, should be YYYY-MM-DDTHH:MM:SSZ")

class HRSIRequest(object):
    '''
    Request HRSI products in the catalogue.
     * https://cryo.land.copernicus.eu/resto/api/collections/HRSI/describe.xml
    '''

    # Request URL root
    URL_ROOT = 'https://cryo.land.copernicus.eu/resto/api/collections/HRSI/search.json'

    # URL parameter: geometry - region of interest, defined as WKT string (POINT, POLYGON, etc.)
    # in WGS84 projection.
    URL_PARAM_GEOMETRY = 'geometry'

    # URL parameters: publishedAfter, publishedBefore - the date limits when the product was
    # published in our repository
    URL_PARAM_PUBLISHED_AFTER = 'publishedAfter'
    URL_PARAM_PUBLISHED_BEFORE = 'publishedBefore'
    
    # URL parameters: startDate, completionDate - the date limits when the sensing was performed
    URL_PARAM_OBSERVATIONDATE_AFTER = 'startDate'
    URL_PARAM_OBSERVATIONDATE_BEFORE = 'completionDate'
    
    # URL parameter : HRSI productIdentifier T32TLR or FSC_20170913T114531_S2B_T29UNV_V001_0
    URL_PARAM_PRODUCT_IDENTIFIER = 'productIdentifier'

    # URL parameter : HRSI product type (FSC/RLIE/PSA/PSA-LAEA/ARLIE).
    URL_PARAM_PRODUCT_TYPE = 'productType'

    # URL parameter : HRSI max cloud coverage.
    URL_PARAM_CLOUD_COVER = 'cloudCover'
    
    # URL parameter : HRSI text search.
    URL_PARAM_TEXTUAL_SEARCH = 'q'

    # URL parameter : result page index.
    URL_PARAM_PAGE_INDEX = 'page'

    # Static URL parameters.
    # status all: request all processed products 
    # maxRecords: request n products per page.
    # dataset: request within ESA-DATASET.
    # sortParam: results are sorted according start date.
    # sortOrder: results are sorted in descending order (most recent first).
    URL_STATIC_PARAMS = {
        'status': 'all',
        'maxRecords': 1000, # max results per page
        'dataset': 'ESA-DATASET',
        'sortParam': 'startDate',
        'sortOrder': 'descending'
    }

    def __init__(self, outputPath):
        self.outputPath = os.path.abspath(outputPath)
        if not os.path.exists(self.outputPath):
            logging.info("Creating directory " + self.outputPath)
            os.makedirs(self.outputPath)
        else:
            logging.warning("Existing directory " + self.outputPath)
        self.hrsi_http_request = None
        self.hrsi_credential = None
        self.result_file = None

    def set_http_request(self, hrsi_http_request):
        logging.info("The query %s will be used to request HR-S&I products."%(hrsi_http_request))
        self.hrsi_http_request = hrsi_http_request

    def set_credential(self, hrsi_credential):
        logging.info("The file %s will be used as credential to enable download."%(hrsi_credential))
        self.hrsi_credential = hrsi_credential

    def set_result_file(self, result_file):
        logging.info("The file %s will be used as list of products to download."%(result_file))
        self.result_file = result_file

    def build_request(self,
                        collection=None,
                        productIdentifier=None,
                        productType=None,
                        obsDateMin=None,
                        obsDateMax=None,
                        publicationDateMin=None,
                        publicationDateMax=None,
                        cloudCoverageMax=None,
                        geometry=None,
                        textualSearch=None ):

        '''
        Build the request to access HR-S&I catalogue.
        :param productIdentifier: text to search in productIdentifier, as string.
        :param productType: product type, as string.
        :param obsDateMin: Min request date, as a datetime object.
        :param obsDateMax: Max request date, as a datetime object.
        :param publicationDateMin: Min publication date, as a datetime object.
        :param publicationDateMax: Max publication date, as a datetime object.
        :param cloudCoverageMax: Max cloud coverag.
        :param geometry: Area Of Interest (AOI) to query, in WGS84 projection, in the WKT format.
        :param textualSearch: Free text search.
        :return: formatted hrsi_http_request.
        '''
        # URL parameters.
        url_params = {}
        if productIdentifier:
            url_params[HRSIRequest.URL_PARAM_PRODUCT_IDENTIFIER] = (
                '%25' + productIdentifier + '%25')
        if productType:
            url_params[HRSIRequest.URL_PARAM_PRODUCT_TYPE] = productType
        if obsDateMin:
            url_params[HRSIRequest.URL_PARAM_OBSERVATIONDATE_AFTER] = \
                validate_Rfc3339(obsDateMin)
        if obsDateMax:
            url_params[HRSIRequest.URL_PARAM_OBSERVATIONDATE_BEFORE] = \
                validate_Rfc3339(obsDateMax)
        if publicationDateMin:
            url_params[HRSIRequest.URL_PARAM_PUBLISHED_AFTER] = \
                validate_Rfc3339(publicationDateMin)
        if publicationDateMax:
            url_params[HRSIRequest.URL_PARAM_PUBLISHED_BEFORE] = \
                validate_Rfc3339(publicationDateMax)
        if cloudCoverageMax:
            url_params[HRSIRequest.URL_PARAM_CLOUD_COVER] = "[0,%s]"%(str(cloudCoverageMax))
        if geometry:
            url_params[HRSIRequest.URL_PARAM_GEOMETRY] = geometry
        if textualSearch:
            url_params[HRSIRequest.URL_PARAM_TEXTUAL_SEARCH] = textualSearch.replace(' ','+')

        if(url_params):
            url_params.update(HRSIRequest.URL_STATIC_PARAMS)
            logging.info("Query parameters: ")
            logging.info(url_params)
            self.set_http_request(HRSIRequest.URL_ROOT + \
                      '?' + \
                      '&'.join(['%s=%s'%(key, value) for key, value in url_params.items()]))
        else:
            logging.error("No query parameters were provided, no query was generated")
            sys.exit(-2)
        return


    def execute_request(self, max_requested_pages=None):
        # Check that the request was set before the call
        if self.hrsi_http_request is None:
            logging.error("No hrsi_http_request was provided or configured")
            sys.exit(-2)

        logging.info("Requesting : " + self.hrsi_http_request)

        # Send page requests, until no results are returned.
        # The results have a 'totalResults' value that we could use, but
        # it gives wrong and inconsistent values.

        # Resulting hrsi_products
        hrsi_products = []

        # Number of requested pages
        requested_pages = 0

        # First exit condition: max number of pages to request is defined,
        # and we have requested enough pages
        def first_exit_condition():
            return (max_requested_pages is not None) and (requested_pages >= max_requested_pages)
        while not first_exit_condition():
            requested_pages += 1
            hrsi_products_aux = self.request_page(self.hrsi_http_request, requested_pages)

            # Second exit condition: no results are returned
            if not hrsi_products_aux:
                break

            # Save results
            hrsi_products += hrsi_products_aux

        # Only keep unique values and check for duplicate products
        total_count = len(hrsi_products)
        logging.debug(total_count, hrsi_products)
        hrsi_products = set(hrsi_products)
        if len(hrsi_products) != total_count:
            logging.warning('Duplicated HRSI products found.')

        logging.info("Found " + str(len(hrsi_products)) + " HR-S&I products.")

        # Save result file in the output folder
        self.set_result_file(os.path.join(self.outputPath, "result_file.txt"))
        logging.info("Listing results in " + self.result_file)
        with open(self.result_file, 'w') as f:
            f.writelines([";".join(res)+"\n" for res in hrsi_products])
        return

    def request_page(self, http_request, page_index):
        '''Request one page of HRSI products (each page contains URL_PAGE_SIZE products).'''
        current_page = http_request + '&page=' + str(page_index)
        logging.info("Processing result page #%s"%(str(page_index)))

        # Send Get request
        response = requests.get(current_page)

        # Read JSON response
        json_root = {}
        if response:
            json_root = response.json()

        # Get features
        try:
            features = json_root["features"]
        except KeyError:
            features = {}
            logging.error('features entry is missing from the JSON response:\n%s'\
                '\nurl parameters requested : \n%s' %(
                json.dumps(json_root, indent=4),
                json.dumps(url_params_page, indent=4)
            ))

        # Resulting hrsi products
        hrsi_products = []

        # Read each feature
        for feature_index, feature in enumerate(features):
            hrsi_products.append(self.read_hrsi_feature(json_root, feature, feature_index))

        # Return the hrsi_products list
        return hrsi_products

    def read_hrsi_feature(self, json_root, feature, feature_index):
        '''Read a HRSI product JSON feature.'''

        # Partial Python function. Then just add the json_param for each call.
        read = partial(
            self.read_json_param,
            json_root, feature, feature_index)

        # Full L1C path in the DIAS catalogue
        hrsi_path = read('productIdentifier')
        hrsi_title = read('title')
        hrsi_obs_date = read('startDate')
        hrsi_product_type = read('productType')
        hrsi_url = read('services')['download']['url']
        hrsi_size = read('services')['download']['size']
        hrsi_publication_date = read('published')
        return (hrsi_url, hrsi_title)

    def read_json_param(self, json_root, feature, feature_index, json_param):
        '''Read a JSON parameter.'''
        try:
            return feature['properties'][json_param]
        except KeyError:
            raise Exception(
                'features[%d][\'properties\'][\'%s\'] entry is missing from the JSON contents:\n%s' %
                (feature_index, json_param, json.dumps(json_root, indent=4)))

    def __get_token__(self, credentials):
        command = ['curl -s -d "client_id=PUBLIC"']
        command.append('-d "username=%s"'%credentials[0])
        command.append('-d "password=%s"'%credentials[1])
        command.append('-d "grant_type=password"')
        command.append('"https://cryo.land.copernicus.eu/auth/realms/cryo/protocol/openid-connect/token"')
        out = eval(subprocess.check_output(" ".join(command), shell=True))
        if 'error' in out:
           logging.error("Following error occured when getting the token: {}".format(out))
        return out['access_token']

    def __hrsi_adress__(self, adress_id, credentials):
        return '%s?token=%s'%(adress_id, self.__get_token__(credentials))

    def download(self):
        # Check that the hrsi_credential was set before the call
        if self.hrsi_credential is None:
            logging.error("No HR-S&I credential file was provided")
            sys.exit(-2)
        #====================
        # read hrsi_credential
        #====================
        try:
            credentials=()
            with open(self.hrsi_credential) as f:
                credentials = f.readline().rstrip().split(':')
        except :
            logging.error("Error while parsing credential file: " + str(self.hrsi_credential))
            raise
            sys.exit(-2)


        # Check that the result file was set before the call
        if self.result_file is None:
            logging.error("No result_file was provided")
            sys.exit(-2)
        #====================
        # read result_file
        #====================
        try:
            with open(self.result_file) as f:
                content = f.readlines()
            product_list = [x.strip().split(';') for x in content if x.strip()]
            
        except :
            logging.error("Error while parsing result_file file: " + str(self.result_file))
            raise
            sys.exit(-2)
        # loop to download all products within the list
        for info_product in product_list:
            start_time = time.time()
            ntries = 0
            max_retry = 1
            while(ntries < max_retry):
                try:
                    # first info must be product url (mandatory)
                    product_url = info_product[0]
                    adress = self.__hrsi_adress__(product_url, credentials)

                    # second info is product name (optional)
                    dl_filename = None
                    if len(info_product) >= 2:
                        dl_filename = '%s.zip'%(info_product[1].split('/')[-1])

                    # start actual download
                    hrsi_filepath = self.download_with_curl(adress, dl_filename)
                    logging.info('Product successfully downloaded at %s (in %s seconds)'\
                                    %(hrsi_filepath, (time.time()-start_time)))
                    break
                except:
                    ntries += 1
                    if ntries == max_retry:
                        raise
                    else:
                        time.sleep(5.*ntries)
                        logging.info('  - try #%d failed, retrying...'%ntries)

    def download_with_curl(self, product_url, dl_filename=None):
        # parse header to read remote filename
        if dl_filename is None:
            import re
            headers = str(subprocess.check_output('curl -sI %s'%(product_url), shell=True))
            dl_filename = re.findall("filename=(\S+)",str(headers))[0].split('\\r')[0]
            assert dl_filename.endswith('.zip')
        # download the product in outputPath
        logging.info(dl_filename + " " + product_url.split("?token")[0])
        hrsi_filepath = os.path.join(self.outputPath, dl_filename)
        logging.debug('DL filepath: ' + hrsi_filepath)
        subprocess.check_call('curl %s -o %s -s'%(product_url, hrsi_filepath), shell=True)
        logging.debug('DL command: ' + 'curl %s -o %s -s'%(product_url, hrsi_filepath))
        return hrsi_filepath

class HRVPPRequest(object):
    '''
    Request HRVPP products in the catalogue.
     * https://phenology.hrvpp.vgt.vito.be/description - for available collections
     * https://phenology.hrvpp.vgt.vito.be/description?collection=... - for product search template
    '''

    # Request URL root
    URL_ROOT = 'http://phenology.hrvpp.vgt.vito.be/products'
    
    URL_PARAM_COLLECTION='collection'

    # URL parameter: geometry - region of interest, defined as WKT string (POINT, POLYGON, etc.)
    # in WGS84 projection.
    URL_PARAM_GEOMETRY = 'geometry'

    # URL parameters: publishedAfter, publishedBefore - the date limits when the product was
    # published in our repository
    URL_PARAM_PUBLISHED = 'publicationDate'
    
    # URL parameters: startDate, completionDate - the date limits when the sensing was performed
    URL_PARAM_OBSERVATIONDATE_AFTER = 'start'
    URL_PARAM_OBSERVATIONDATE_BEFORE = 'end'
    
    # URL parameter : productIdentifier (no wildcard) e.g. VI_20191220T115511_S2A_T29UNU-010m_V100_NDVI
    URL_PARAM_PRODUCT_IDENTIFIER = 'uid'

    # URL parameter : HRVPP product type (NDVI, LAI, PPI, QFLAG2, SOSD, EOSD,...)
    URL_PARAM_PRODUCT_TYPE = 'productType'

    # URL parameter : HRSI max cloud coverage.
    # URL_PARAM_CLOUD_COVER = 'cloudCover'
    
    # URL parameter : HRSI text search.
    URL_PARAM_TEXTUAL_SEARCH = 'q'

    # URL parameter : result page index.
    URL_PARAM_PAGE_INDEX = 'startPage'

    # URL parameter to filter on Sentinel-2 tile
    URL_PARAM_TILE = 'tileId'

    # Static URL parameters.
    # count: request at most n products per page.
    # sortKeys: results are sorted by product identifier
    URL_STATIC_PARAMS = {
        'count': 200,
        'sortKeys': 'uid'
    }

    def __init__(self, outputPath):
        self.outputPath = os.path.abspath(outputPath)
        if not os.path.exists(self.outputPath):
            logging.info("Creating directory " + self.outputPath)
            os.makedirs(self.outputPath)
        else:
            logging.warning("Existing directory " + self.outputPath)
        self.hrvpp_http_request = None
        self.hrvpp_credential = None
        self.result_file = None

    def set_http_request(self, hrvpp_http_request):
        logging.info("The query %s will be used to request HR-VPP products."%(hrvpp_http_request))
        self.hrvpp_http_request = hrvpp_http_request

    def set_credential(self, hrvpp_credential):
        logging.info("The file %s will be used as credential to enable download."%(hrvpp_credential))
        self.hrvpp_credential = hrvpp_credential

    def set_result_file(self, result_file):
        logging.info("The file %s will be used as list of products to download."%(result_file))
        self.result_file = result_file

    def build_request(self,
                        collection,
                        productIdentifier=None,
                        productType=None,
                        obsDateMin=None,
                        obsDateMax=None,
                        publicationDateMin=None,
                        publicationDateMax=None,
                        cloudCoverageMax=None,
                        geometry=None,
                        textualSearch=None ):
        '''
        Build the request to access HR-VPP catalogue.
        :param collection: product collection identifier
        :param productIdentifier: productIdentifier, as string.
        :param productType: product type, as string.
        :param obsDateMin: Min request date, as a datetime object.
        :param obsDateMax: Max request date, as a datetime object.
        :param publicationDateMin: Min publication date, as a datetime object.
        :param publicationDateMax: Max publication date, as a datetime object.
        :param cloudCoverageMax: Max cloud coverag.
        :param geometry: Area Of Interest (AOI) to query, in WGS84 projection, in the WKT format.
        :param textualSearch: Free text search.
        :return: formatted http_request.
        '''
        # URL parameters.
        url_params = {}
        
        url_params[HRVPPRequest.URL_PARAM_COLLECTION] = collection
        
        if productIdentifier:
            if len(productIdentifier)==6 and productIdentifier.upper()[0]=='T':
                url_params[HRVPPRequest.URL_PARAM_TILE] = productIdentifier[1:]
            elif len(productIdentifier)==5:
                url_params[HRVPPRequest.URL_PARAM_TILE] = productIdentifier
            else:
                url_params[HRVPPRequest.URL_PARAM_PRODUCT_IDENTIFIER] = (
                    productIdentifier )

        if productType:
            url_params[HRVPPRequest.URL_PARAM_PRODUCT_TYPE] = productType
        
        if obsDateMin:
            url_params[HRVPPRequest.URL_PARAM_OBSERVATIONDATE_AFTER] = \
                validate_Rfc3339(obsDateMin)
        if obsDateMax:
            url_params[HRVPPRequest.URL_PARAM_OBSERVATIONDATE_BEFORE] = \
                validate_Rfc3339(obsDateMax)
        
        if publicationDateMin:
            url_params[HRVPPRequest.URL_PARAM_PUBLISHED] = \
                '['+validate_Rfc3339(publicationDateMin)
        if publicationDateMax:
            url_params[HRVPPRequest.URL_PARAM_PUBLISHED] = \
                validate_Rfc3339(publicationDateMax) + ']'
        
        # cloudCoverPercentage to be implemented by HRVPP based on new QFLAG2 definition
        
        # if cloudCoverageMax:
        #     url_params[HRVPPRequest.URL_PARAM_CLOUD_COVER] = "[0,%s]"%(str(cloudCoverageMax))
        
        if geometry:
            url_params[HRVPPRequest.URL_PARAM_GEOMETRY] = geometry
        if textualSearch:
            url_params[HRVPPRequest.URL_PARAM_TEXTUAL_SEARCH] = textualSearch.replace(' ','+')

        if(url_params):
            url_params.update(HRVPPRequest.URL_STATIC_PARAMS)
            logging.info("Query parameters: ")
            logging.info(url_params)
            self.set_http_request(HRVPPRequest.URL_ROOT + \
                      '?' + \
                      '&'.join(['%s=%s'%(key, value) for key, value in url_params.items()]))
        else:
            logging.error("No query parameters were provided, no query was generated")
            sys.exit(-2)
        return


    def execute_request(self, max_requested_pages=None):
        # Check that the request was set before the call
        if self.hrvpp_http_request is None:
            logging.error("No hrvpp_http_request was provided or configured")
            sys.exit(-2)

        logging.info("Requesting : " + self.hrvpp_http_request)

        # Send page requests, until no results are returned or 
        # or we reach the totalResults total number of results found

        # Resulting hrsi_products
        hrvpp_products = []

        # Requested page
        requested_page = 0

        # First exit condition: max number of pages to request is defined,
        # and we have requested enough pages
        def first_exit_condition():
            return (max_requested_pages is not None) and (requested_page >= max_requested_pages)
        while not first_exit_condition():
            requested_page += 1
            hrvpp_products_aux, total = self.request_page(self.hrvpp_http_request, requested_page)

            # Second exit condition: no results are returned
            if not hrvpp_products_aux:
                break

            # Save results
            hrvpp_products += hrvpp_products_aux
            
            if len(hrvpp_products) == total:
                break

        # Only keep unique values and check for duplicate products
        total_count = len(hrvpp_products)
        logging.debug(total_count, hrvpp_products)
        hrvpp_products = set(hrvpp_products)
        if len(hrvpp_products) != total_count:
            logging.warning('Duplicated HRSI products found.')

        logging.info("Found " + str(len(hrvpp_products)) + " HR-VPP products.")

        # Save result file in the output folder
        self.set_result_file(os.path.join(self.outputPath, "result_file.txt"))
        logging.info("Listing results in " + self.result_file)
        with open(self.result_file, 'w') as f:
            f.writelines([";".join(res)+"\n" for res in hrvpp_products])
        return

    def request_page(self, http_request, page_index):
        '''Request one page of HRVPP products (each page contains URL_PAGE_SIZE products).'''
        current_page = http_request + '&' + HRVPPRequest.URL_PARAM_PAGE_INDEX+'=' + str(page_index)
        logging.info("Processing result page #%s"%(str(page_index)))

        logging.info("current_page "+current_page)
        # Send Get request
        response = requests.get(current_page, timeout=15)

        logging.info("Request completed")

        # Read JSON response
        json_root = {}
        if response:
            json_root = response.json()

        # Get features
        try:
            features = json_root["features"]
        except KeyError:
            features = {}
            logging.error('features entry is missing from the JSON response:\n%s'\
                '\nurl parameters requested : \n%s' %(
                json.dumps(json_root, indent=4),
                json.dumps(current_page, indent=4)
            ))

        # Resulting hrvpp products
        hrvpp_products = []

        # Read each feature
        for feature_index, feature in enumerate(features):
            hrvpp_products.append(self.read_hrvpp_feature(json_root, feature, feature_index))

        # Return the hrsi_products list
        return hrvpp_products, json_root['totalResults']

    def read_hrvpp_feature(self, json_root, feature, feature_index):
        '''Read a HRVPP product JSON feature.'''

        # Partial Python function. Then just add the json_param for each call.
        read = partial(
            self.read_json_param,
            json_root, feature, feature_index)

        # Un-used: file path, observation (start) date, productType
        # hrvpp_path = read('links')['data']['href']
        # hrvpp_obs_date = read('acquisitionInformation')['acquisitionParameters']['beginningDateTime']
        # hrvpp_product_type = read('productInformation')['productType']
        
        hrvpp_id = read('identifier')
        hrvpp_links = read('links')
        hrvpp_url = hrvpp_links['data'][0]['href']
        hrvpp_size = hrvpp_links['data'][0]['length']
        #hrvpp_publication_date = read('published')

        return (hrvpp_url, hrvpp_id+'.tif')

    def read_json_param(self, json_root, feature, feature_index, json_param):
        '''Read a JSON parameter.'''
        try:
            return feature['properties'][json_param]
        except KeyError:
            raise Exception(
                'features[%d][\'properties\'][\'%s\'] entry is missing from the JSON contents:\n%s' %
                (feature_index, json_param, json.dumps(json_root, indent=4)))

    # Example request:
    # curl -X POST -H "Content-Type: application/x-www-form-urlencoded" -d "username=$USER" -d "password=$PASSWORD" -d "grant_type=password" -d "client_id=oscars-download" -d "client_secret=e5c2a18d-1691-4dff-9204-fe3d10b2f4cc" "https://sso.vgt.vito.be/auth/realms/terrascope/protocol/openid-connect/token"

    def __get_token__(self, credentials):
        command = ['curl -s -X POST -H "Content-Type: application/x-www-form-urlencoded"']
        command.append('-d "username=%s"'%credentials[0])
        command.append('-d "password=%s"'%credentials[1])
        command.append('-d "grant_type=password"')
        command.append('-d "client_id=oscars-download"')
        command.append('-d "client_secret=e5c2a18d-1691-4dff-9204-fe3d10b2f4cc"')
        command.append('"https://sso.vgt.vito.be/auth/realms/terrascope/protocol/openid-connect/token"')
        logging.debug("Curl command to receive token: " + " ".join(command))
        out = eval(subprocess.check_output(" ".join(command), shell=True))
        if 'error' in out:
           logging.error("Following error occured when getting the token: {}".format(out))
        return out['access_token']

    def __hrvpp_adress__(self, adress_id, credentials):
        return '%s?token=%s'%(adress_id, self.__get_token__(credentials))

    def download(self):
        # Check that the hrsi_credential was set before the call
        if self.hrvpp_credential is None:
            logging.error("No HR-VPP credential file was provided")
            sys.exit(-2)
        #====================
        # read hrvpp_credential
        #====================
        try:
            credentials=()
            with open(self.hrvpp_credential) as f:
                credentials = f.readline().rstrip().split(':')
        except :
            logging.error("Error while parsing credential file: " + str(self.hrvpp_credential))
            raise
            sys.exit(-2)

        logging.info("Retrieving security token")

        # get security token
        myToken = self.__get_token__(credentials)

        # Check that the result file was set before the call
        if self.result_file is None:
            logging.error("No result_file was provided")
            sys.exit(-2)

        #====================
        # read result_file
        #====================
        logging.info("Reading list of files to download in result_file")
        try:
            with open(self.result_file) as f:
                content = f.readlines()
            product_list = [x.strip().split(';') for x in content if x.strip()]
        except :
            logging.error("Error while parsing result_file file: " + str(self.result_file))
            raise
            sys.exit(-2)

        # warn about downloading large numbers of files
        max_files=200
        if len(product_list) > max_files:
            logging.warn("Downloading more than "+str(max_files)+" files. This can be slow and take up a significant amount of disk space.")
        
        logging.info("Download starts")

        # loop to download all products within the list
        for info_product in product_list:
            start_time = time.time()
            ntries = 0
            max_retry = 1
            while(ntries < max_retry):
                try:
                    # first info must be product url (mandatory)
                    product_url = info_product[0]
                    #adress = self.__hrvpp_adress__(product_url, credentials)
                    # token is not passed as URL parameter, but rather through HTTP request header
                    adress = product_url

                    # second info is product name (optional)
                    dl_filename = None
                    if len(info_product) >= 2:
                        dl_filename = '%s'%(info_product[1].split('/')[-1])

                    # start actual download
                    hrvpp_filepath = self.download_with_curl(adress, dl_filename, header_token=myToken)
                    logging.info('Product successfully downloaded at %s (in %s seconds)'\
                                    %(hrvpp_filepath, (time.time()-start_time)))
                    time.sleep(0.5)
                    break
                except:
                    ntries += 1
                    if ntries == max_retry:
                        raise
                    else:
                        time.sleep(5.*ntries)
                        logging.info('  - try #%d failed, retrying...'%ntries)

    def download_with_curl(self, product_url, dl_filename=None, header_token=None):
        # parse header to read remote filename -> handled by curl's -J options
        #if dl_filename is None:
        #    import re
        #    headers = str(subprocess.check_output('curl -sI %s'%(product_url), shell=True))
        #    dl_filename = re.findall("filename=(\S+)",str(headers))[0].split('\\r')[0]
        #    assert dl_filename.endswith('.tif')
        # download the product in outputPath
        logging.info('Retrieving '+dl_filename)

        hrvpp_filepath = os.path.join(self.outputPath, dl_filename)

        DL_cmd = ["curl","--retry 3","-f -s -# -J -O"]
        if header_token:
            DL_cmd.append('-H "Authorization: Bearer '+header_token+'"')
        DL_cmd.append(product_url)
        DL_cmd = " ".join(DL_cmd)

        logging.debug('DL filepath: ' + hrvpp_filepath)
        logging.debug('DL product_url: ' + product_url)
        logging.debug('DL command: ' + DL_cmd)
        #subprocess.check_call('curl %s -o %s -s'%(product_url, hrvpp_filepath), shell=True)
        subprocess.check_call(DL_cmd, shell=True)
        return hrvpp_filepath


def main():

    parser = argparse.ArgumentParser(description="""This script provides query and download capabilities for the HR-S&I and HR-VPP products, there are three possible modes (query|query_and_download|download), see example usages below:\n
    > python CLMS_downloader.py output_folder -query -productType FSC -productIdentifier 31TCH -obsDateMin 2020-06-01T00:00:00Z -obsDateMax 2020-06-30T00:00:00Z\n
    > python CLMS_downloader.py output_folder -credentials auth.txt -query_and_download -queryURL "https://cryo.land.copernicus.eu/resto/api/collections/HRSI/search.json?maxRecords=1000&publishedAfter=2020-06-29T00:00:00Z&publishedBefore=2020-06-30T00:00:00Z&productType=FSC"\n
    > python CLMS_downloader.py output_folder -credentials auth.txt -download -result_file result_file.txt\n""", formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument("output_dir", help="output directory to store products")

    parser.add_argument("service",help="HRSI|HRVPP")

    # Exclusive modes available
    group_mode = parser.add_argument_group("execution mode")
    group_mode_ex = group_mode.add_mutually_exclusive_group(required=True)
    group_mode_ex.add_argument("-query", dest='query', action='store_true', help="only query and list the corresponding products according the query_params, a result file is created in output_dir.")
    group_mode_ex.add_argument("-query_and_download", dest='query_and_download', action='store_true', help="query and download according the query_params, a result file is created and products are downloaded in output_dir.")
    group_mode_ex.add_argument("-download", dest='download', action='store_true', help="only download products in output_dir, using an existing file with download URLs.")


    # Parameters used to define a query, to use a query generated through the HR-S&I finder or to build a new one
    group_query = parser.add_argument_group("query_params", "mandatory parameters for query and query_and_download modes")
    group_query.add_argument("-queryURL", type=str, help="Catalogue search query, that may be copied from portal. If no query is provided, other query_params are used to build one from scratch.")
    group_query.add_argument("-productIdentifier", type=str, help="\"T32TLR\" or \"FSC_20170913T114531_S2B_T29UNV_V001_0\" or \"VI_20191220T115511_S2A_T29UNU-010m_V100_NDVI\".")
    group_query.add_argument("-productType", type=str, help="One of FSC|RLIE|PSA|PSA_LAEA|ARLIE for HRSI, one of 20 parameters (NDVI, LAI, PPI, SOSD, EODS, etc) for HRVPP")
    group_query.add_argument("-obsDateMin", type=str, help="2020-06-02T00:00:00Z")
    group_query.add_argument("-obsDateMax", type=str, help="2020-06-02T00:00:00Z")
    group_query.add_argument("-publicationDateMin", type=str, help="2020-06-02T00:00:00Z")
    group_query.add_argument("-publicationDateMax", type=str, help="2020-06-02T00:00:00Z")
    group_query.add_argument("-cloudCoverageMax", type=int, help="0-100 (percent) - for HRSI only")
    group_query.add_argument("-textualSearch", type=str, help="\"Winter in Finland\"")
    group_query.add_argument("-geometry", type=str, help="WKT geometry as text")
    group_query.add_argument("-collection", type=str, help="Product collection (mandatory for HRVPP service)")


    # Parameters to download products from urls obtained
    group_download = parser.add_argument_group("download_params", "mandatory parameters for query_and_download or download modes")
    group_download.add_argument("-credentials", type=str, \
        help='text file containing valid login and password (required for all downloading operations) in the following format: \"login:password\"')
    group_download.add_argument("-result_file", type=str, \
        help="to use the result file from previous query or containing multiple copied urls (required only for download mode)")

    args = parser.parse_args()

    # Init Request
    service = args.service.upper()

    if args.service=='HRSI':
        myRequest = HRSIRequest(args.output_dir)
        # HRS&I catalogue has no notion of "collection"
        if args.collection:
            args.collection=None
    else:
        myRequest = HRVPPRequest(args.output_dir)
        # HRVPP catalogue has no notion (yet) of cloudCover %, 
        # as this remains to be computed
        if args.cloudCoverageMax:
            args.cloudCoverageMax = None
        # collection is mandatory
        if not args.collection:
            logging.error("Collection is mandatory")

    # Query mode
    if args.query or args.query_and_download:
        # First check if no query is provided as input.
        if args.queryURL:
            # Set the configured http request
            myRequest.set_http_request(args.queryURL)
        # Build custom query, when http_request is empty.
        else:
            http_request = myRequest.build_request(
                                collection=args.collection,
                                productIdentifier=args.productIdentifier,
                                productType=args.productType,
                                obsDateMin=args.obsDateMin,
                                obsDateMax=args.obsDateMax,
                                publicationDateMin=args.publicationDateMin,
                                publicationDateMax=args.publicationDateMax,
                                cloudCoverageMax=args.cloudCoverageMax,
                                geometry=args.geometry,
                                textualSearch=args.textualSearch)


        # Query HTTP API to list results
        myRequest.execute_request()

    # Switch to download from file mode (if enable)
    if args.download:
        if args.result_file:
            myRequest.set_result_file(args.result_file)
        else:
            logging.error("No result file was provided")

    # Switch actual result download (if enable)
    if args.query_and_download or args.download:
        logging.info("Start download mode")
        myRequest.set_credential(args.credentials)
        myRequest.download();
        logging.info("Download complete!")
    else:
        logging.info("No products were downloaded.")

    logging.info("End.")


if __name__ == "__main__":
    # Set logging level and format.
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format= \
        '%(asctime)s - %(filename)s:%(lineno)s - %(levelname)s - %(message)s')
    main()

