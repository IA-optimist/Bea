import { useEffect, useState } from 'react';
import { Package, Rocket, Search, Filter, ExternalLink } from 'lucide-react';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { Badge } from '../components/Badge';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { apiClient } from '../api/client';
import { formatCurrency, formatDateTime } from '../utils/format';
import type { Product } from '../types';

export const Products = () => {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [deployingIds, setDeployingIds] = useState<Set<string>>(new Set());
  const [searchTerm, setSearchTerm] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  useEffect(() => {
    loadProducts();
  }, [page, categoryFilter, statusFilter]);

  const loadProducts = async () => {
    try {
      setLoading(true);
      const params: any = { page, per_page: 12 };
      
      if (categoryFilter !== 'all') params.category = categoryFilter;
      if (statusFilter !== 'all') params.status = statusFilter;

      const data = await apiClient.getProducts(params);
      setProducts(data.items);
      setTotalPages(data.total_pages);
    } catch (err) {
      console.error('Failed to load products:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleDeploy = async (id: string) => {
    try {
      setDeployingIds((prev) => new Set(prev).add(id));
      const result = await apiClient.deployProduct(id);
      alert(`Deployment started! Job ID: ${result.job_id}`);
      
      // Poll for status updates
      setTimeout(() => {
        loadProducts();
        setDeployingIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }, 3000);
    } catch (err) {
      console.error('Failed to deploy product:', err);
      alert('Failed to deploy product');
      setDeployingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const getStatusVariant = (status: string) => {
    switch (status) {
      case 'deployed':
        return 'success';
      case 'deploying':
        return 'warning';
      case 'active':
        return 'info';
      case 'inactive':
        return 'error';
      default:
        return 'default';
    }
  };

  const filteredProducts = products.filter((product) =>
    product.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    product.description.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Products</h1>
          <p className="text-gray-600 dark:text-gray-400 mt-1">
            Manage and deploy your AI-powered products
          </p>
        </div>
      </div>

      {/* Filters */}
      <Card>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search products..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>

          {/* Category Filter */}
          <div className="relative">
            <Filter className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="all">All Categories</option>
              <option value="ai">AI & ML</option>
              <option value="automation">Automation</option>
              <option value="analytics">Analytics</option>
              <option value="integration">Integration</option>
            </select>
          </div>

          {/* Status Filter */}
          <div className="relative">
            <Package className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="all">All Status</option>
              <option value="active">Active</option>
              <option value="deployed">Deployed</option>
              <option value="deploying">Deploying</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
        </div>
      </Card>

      {/* Products Grid */}
      {loading ? (
        <LoadingSpinner />
      ) : filteredProducts.length === 0 ? (
        <Card>
          <div className="text-center py-12">
            <Package className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
              No products found
            </h3>
            <p className="text-gray-600 dark:text-gray-400">
              {searchTerm ? 'Try adjusting your search criteria' : 'Create your first product to get started'}
            </p>
          </div>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredProducts.map((product) => (
              <Card key={product.id} className="flex flex-col">
                <div className="flex-1 space-y-4">
                  {/* Header */}
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-12 h-12 bg-gradient-to-br from-primary-500 to-primary-600 rounded-lg flex items-center justify-center">
                        <Package className="w-6 h-6 text-white" />
                      </div>
                      <div>
                        <h3 className="font-semibold text-gray-900 dark:text-white">
                          {product.name}
                        </h3>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          v{product.version}
                        </p>
                      </div>
                    </div>
                    <Badge variant={getStatusVariant(product.status)}>{product.status}</Badge>
                  </div>

                  {/* Description */}
                  <p className="text-sm text-gray-600 dark:text-gray-400 line-clamp-3">
                    {product.description}
                  </p>

                  {/* Metadata */}
                  <div className="flex items-center justify-between text-sm">
                    <Badge>{product.category}</Badge>
                    <span className="font-semibold text-gray-900 dark:text-white">
                      {formatCurrency(product.price)}
                    </span>
                  </div>

                  {/* Deployment URL */}
                  {product.deployment_url && (
                    <a
                      href={product.deployment_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-2 text-sm text-primary-600 dark:text-primary-400 hover:underline"
                    >
                      <ExternalLink className="w-4 h-4" />
                      View Deployment
                    </a>
                  )}

                  {/* Footer */}
                  <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
                    <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                      Created {formatDateTime(product.created_at)}
                    </p>
                    
                    {/* Actions */}
                    <div className="flex gap-2">
                      {product.status !== 'deployed' && product.status !== 'deploying' && (
                        <Button
                          onClick={() => handleDeploy(product.id)}
                          loading={deployingIds.has(product.id)}
                          className="flex-1"
                          size="sm"
                        >
                          <Rocket className="w-4 h-4" />
                          Deploy
                        </Button>
                      )}
                      {product.status === 'deploying' && (
                        <Button variant="secondary" disabled className="flex-1" size="sm">
                          <div className="w-4 h-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin"></div>
                          Deploying...
                        </Button>
                      )}
                      {product.status === 'deployed' && (
                        <Button variant="secondary" disabled className="flex-1" size="sm">
                          <Rocket className="w-4 h-4" />
                          Deployed
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <Card>
              <div className="flex items-center justify-between">
                <Button
                  variant="ghost"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  Previous
                </Button>
                <span className="text-sm text-gray-600 dark:text-gray-400">
                  Page {page} of {totalPages}
                </span>
                <Button
                  variant="ghost"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                >
                  Next
                </Button>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
};
