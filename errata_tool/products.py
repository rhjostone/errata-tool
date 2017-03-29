import copy

from errata_tool import ErrataException, ErrataConnector
from errata_tool import security  # NOQA

#
# Change this if you change the structure of the tables we assemble
# here.  This is added to export() and checked on import().
#
_product_table_version = 1


class ProductList(ErrataConnector):
    def __init__(self, **kwargs):
        self.releases = {}
        self.products = {}
        self.versions = {}
        self.product_ids = {}

        #
        # Because this is a lot of data to pull, allow
        # users to pass in import/export functions
        #
        # User defined save function. Takes one argument:
        # the data returned from self.export().
        #
        self.__save = None

        #
        # User defined restore function.  Takes no arguments.
        # Returns a copy of information that was previously
        # created using self.export()
        #
        # If the format is wrong, the information is loaded
        # from Errata.
        #
        self.__load = None

        if 'save' in kwargs and callable(kwargs['save']):
            # print 'Save function specified'
            self.__save = kwargs['save']

        if 'load' in kwargs and callable(kwargs['load']):
            # print 'Load function specified'
            self.__load = kwargs['load']
            blob = self.__load()
            if blob is not None and self.restore(blob):
                return

        if 'fetch' in kwargs and kwargs['fetch'] is False:
            return

        # print 'Loading it the slow way'
        self.fetch_products()
        self.fetch_all_versions()
        self.fetch_releases()
        self.coallate_data()
        if self.__save is not None:
            self.__save(self.export())

    def __str__(self):
        return 'Product Information, version ' + str(_product_table_version)

    def export(self):
        export_info = {}
        export_info['name'] = 'errata_tool_products'
        export_info['prodinfo_version'] = _product_table_version
        export_info['products'] = copy.deepcopy(self.products)
        export_info['versions'] = copy.deepcopy(self.versions)
        export_info['releases'] = copy.deepcopy(self.releases)
        export_info['product_ids'] = copy.deepcopy(self.product_ids)
        return export_info

    #
    # Restore from a dict that matches what self.export() would
    # provide. Returns False if the version is incorrect or there
    # are missing fields.
    #
    def restore(self, import_info):
        if type(import_info) is not dict:
            raise ValueError('import_info is not a dict')
        if 'name' not in import_info or \
                'prodinfo_version' not in import_info or \
                'products' not in import_info or \
                'versions' not in import_info or \
                'releases' not in import_info or \
                'product_ids' not in import_info:
            raise ValueError('Malformed import_info')

        if import_info['prodinfo_version'] != _product_table_version:
            return False

        # Don't use references to existing tables
        self.products = copy.deepcopy(import_info['products'])
        self.versions = copy.deepcopy(import_info['versions'])
        self.releases = copy.deepcopy(import_info['releases'])
        self.product_ids = copy.deepcopy(import_info['product_ids'])

        return True

    #
    # Fetch product information. This is a "paginated" API where
    # one must fetch until there are no more entries, then parse
    # each "page" individually.
    #
    def fetch_releases(self):
        page = 1
        releases = {}
        while True:
            ret = self._get('/api/v1/releases?page[number]=' + str(page))
            if ret is None:
                break
            if 'data' not in ret:
                raise ErrataException('Malformed response from server')
            if len(ret['data']) == 0:
                break

            for r in ret['data']:
                attrs = r['attributes']
                if r['type'] != 'releases' or not attrs['enabled']:
                    continue

                #
                # Ignore this specific release (intentional)
                #
                if r['id'] == 21:
                    continue

                info = {}
                info['id'] = int(r['id'])
                info['name'] = attrs['name']
                info['description'] = attrs['description']
                info['async'] = attrs['is_async']

                info['brew_tags'] = {}
                for t in r['relationships']['brew_tags']:
                    info['brew_tags'][int(t['id'])] = t['name']

                info['versions'] = {}
                info['products'] = {}
                for t in r['relationships']['product_versions']:
                    info['versions'][int(t['id'])] = t['name']

                releases[int(r['id'])] = info

            page = page + 1
        self.releases = releases

    #
    # Fetch product information
    #
    def fetch_products(self):
        ret = self._get('/products.json')

        self.products = {}

        for p in ret:
            try:
                product = p['product']
            except KeyError:
                continue
            if int(product['isactive']) == 0:
                continue
            info = {}
            pid = int(product['id'])
            info['id'] = pid
            info['name'] = str(product['name'])
            info['short_name'] = str(product['short_name'])
            if str(product['short_name']) in self.products:
                raise ValueError('Duplicate product:' +
                                 str(product['short_name']))
            info['versions'] = {}
            info['releases'] = {}
            self.products[pid] = info
            self.product_ids[str(product['short_name'])] = pid

    #
    # Fetch versions for a product.
    # Pre: Need product table created by fetch_products()
    #
    def fetch_versions(self, prod):
        if type(prod) is str:
            prod = self.product_ids[prod]

        ret = self._get('/products/' + str(prod) + '/product_versions.json')
        versions = {}
        for v in ret:
            release = v['product_version']
            if int(release['enabled']) == 0:
                continue

            info = {}
            n = int(release['id'])
            info['name'] = release['name']
            info['brew_tag'] = release['default_brew_tag']
            info['description'] = release['description']
            info['id'] = release['id']
            info['releases'] = {}
            info['products'] = {}
            self.versions[n] = info
            versions[n] = release['name']
        self.products[prod]['versions'] = versions

    #
    # Fetch versions for a product.
    # Pre: Need product table created by fetch_products()
    #
    def fetch_all_versions(self):
        for p in self.products:
            n = self.products[p]['short_name']
            self.fetch_versions(n)

    #
    # Build up links between products/releases/versions
    # Pre: fetch_products(), fetch_all_versions()
    #
    def coallate_data(self):
        #
        # Link up products and releases
        #
        for p in self.products:
            prod = self.products[p]
            prod['releases'] = {}
            for v in prod['versions']:
                self.versions[v]['releases'] = {}
                for r in self.releases:
                    rel = self.releases[r]
                    if rel['id'] in prod['releases']:
                        rel['products'][prod['id']] = prod['name']
                    for rv in rel['versions']:
                        self.versions[v]['products'][prod['id']] = prod['name']
                        if v == rv:
                            # Append release ID on product...
                            prod['releases'][r] = rel['name']
                            # And tie to specific version...
                            self.versions[v]['releases'][r] = rel['name']

    def _prune_releases(self, releases, **kwargs):
        if releases is None:
            return None
        if 'async' not in kwargs or kwargs['async'] is True:
            return releases
        ret = {}
        for r in releases:
            if self.releases[r]['async'] is True:
                continue
            ret[r] = releases[r]
        return ret

    #
    # Return a dict of releases in the form of:
    #  { id: 'name', id2: 'name2' }
    #
    def get_releases(self, product, **kwargs):
        prod = self.__getitem__(product)
        ret = None

        if 'version' not in kwargs:
            ret = prod['releases']
        else:
            version = kwargs['version']
            if type(version) is int:
                ret = prod['versions'][version]['releases']
            elif type(version) is not str:
                raise ValueError('Product must be an ID or string')
            else:
                for v in prod['versions']:
                    if prod['versions'][v]['name'] == version:
                        ret = prod['versions'][v]['releases']
                        break
        releases = {}
        for x in ret:
            releases[x] = self.releases[x]['name']
        return self._prune_releases(releases, **kwargs)

    #
    # Return a dict of releases in the form of:
    #  { id: 'name', id2: 'name2' }
    #
    def get_releases_by_name(self, product, **kwargs):
        ret = self.get_releases(product, **kwargs)
        return {val: key for key, val in ret.items()}

    #
    # Return a dict of releases in the form of:
    #  { id: 'name', id2: 'name2' }
    #
    def get_versions(self, product, **kwargs):
        prod = self.__getitem__(product)
        return prod['versions']

    #
    # Return a dict of releases in the form of:
    #  { 'name': id, 'name2': id2 }
    #
    def get_versions_by_name(self, product, **kwargs):
        ret = self.get_versions(product, **kwargs)
        return {val: key for key, val in ret.items()}

    def __getitem__(self, prod):
        if type(prod) is int:
            if prod not in self.products:
                raise ValueError('No such product: ' + str(prod))
            return self.products[prod]

        if type(prod) is str:
            return self.products[self.product_ids[prod]]

        raise ValueError('No such product: ' + str(prod))