# Code Author
# Yuta Nakahara <yuta.nakahara@aoni.waseda.jp>
# Document Author
# Yuta Nakahara <yuta.nakahara@aoni.waseda.jp>
# Wenbin Yu <ywb827748728@163.com>
import warnings
import copy
import pickle
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import rgb2hex
from sklearn import tree as sklearn_tree
from sklearn.ensemble import RandomForestClassifier
from sklearn.ensemble import RandomForestRegressor

from .. import base
from .._exceptions import ParameterFormatError, DataFormatError, CriteriaError, ResultWarning, ParameterFormatWarning
from .. import _check
from .. import bernoulli, categorical, normal, multivariate_normal, linearregression, poisson, exponential

_CMAP = plt.get_cmap("Blues")
MODELS = {
    bernoulli,
    # categorical,
    normal,
    # multivariate_normal,
    # linearregression,
    poisson,
    exponential,
    }
DISCRETE_MODELS = {
    bernoulli,
    # categorical,
    poisson,
    }
CONTINUOUS_MODELS = {
    normal,
    # multivariate_normal,
    # linearregression,
    exponential,
    }

class _Node:
    """ The node class used by generative model and the prior distribution

    Parameters
    ----------
    depth : int
            a non-negetive integer :math:' >= 0'
    k_candidates : list
            feature value which can be used to split node
    h_g : float
            a positive real number  in \[0 , 1 \], by default 0.5
    k : int
            a positive integer, by default None
    sub_model : class
            a class of generative model assigned to leaf nodes
    """
    def __init__(self,
                 depth,
                 c_num_children,
                 k_candidates=None,
                 h_g=0.5,
                 k=None,
                 sub_model=None,
                 leaf=False,
                 map_leaf=False
                 ):
        self.depth = depth
        self.children = [None for i in range(c_num_children)]  # child nodes
        self.k_candidates = k_candidates
        self.h_g = h_g
        self.k = k
        self.sub_model = sub_model
        self.leaf = leaf
        self.map_leaf = map_leaf

class GenModel(base.Generative):
    """ The stochastice data generative model and the prior distribution

    Parameters
    ----------
    c_k : int
        A positive integer
    c_d_max : int, optional
        A positive integer, by default 10
    c_num_children : int, optional
        A positive integer, by default 2
    SubModel : class, optional
        bernoulli, poisson, normal, or exponential, 
        by default bernoulli
    root : metatree._Node, optional
        A root node of a meta-tree, 
        by default a tree consists of only one node.
    h_k_prob_vec : numpy.ndarray, optional
        A vector of real numbers in :math:`[0, 1]`, 
        by default [1/c_k, 1/c_k, ... , 1/c_k]
        Sum of its elements must be 1.0.
    h_g : float, optional
        A real number in :math:`[0, 1]`, by default 0.5
    sub_h_params : dict, optional
        h_params for self.SubModel.GenModel, by default {}
    h_metatree_list : list of metatree._Node, optional
        Root nodes of meta-trees, by default []
    h_metatree_prob_vec : numpy.ndarray, optional
        A vector of real numbers in :math:`[0, 1]` 
        that represents prior distribution of h_metatree_list, 
        by default uniform distribution
        Sum of its elements must be 1.0.
    seed : {None, int}, optional
        A seed to initialize numpy.random.default_rng(),
        by default None
    """
    def __init__(
            self,
            c_k,
            c_d_max=10,
            c_num_children=2,
            *,
            SubModel=bernoulli,
            root=None,
            h_k_prob_vec = None,
            h_g=0.5,
            sub_h_params={},
            h_metatree_list=[],
            h_metatree_prob_vec=None,
            seed=None,
            ):
        # constants
        self.c_d_max = _check.pos_int(c_d_max,'c_d_max',ParameterFormatError)
        self.c_num_children = _check.pos_int(c_num_children,'c_num_children',ParameterFormatError)
        self.c_k = _check.pos_int(c_k,'c_k',ParameterFormatError)
        if SubModel not in MODELS:
            raise(ParameterFormatError(
                "SubModel must be bernoulli, "
                +"poisson, normal, or exponential."
            ))
        self.SubModel = SubModel
        self.rng = np.random.default_rng(seed)

        # h_params
        self.h_k_prob_vec = np.ones(self.c_k) / self.c_k
        self.h_g = 0.5
        self.sub_h_params = {}
        self.h_metatree_list = []
        self.h_metatree_prob_vec = None

        self.set_h_params(
            h_k_prob_vec,
            h_g,
            sub_h_params,
            h_metatree_list,
            h_metatree_prob_vec,
        )

        # params
        self.root = _Node(
            0,
            self.c_num_children,
            list(range(self.c_k)),
            self.h_g,
            sub_model=self.SubModel.GenModel(seed=self.rng,**self.sub_h_params),
            leaf=True
            )

        self.set_params(root)

    def _gen_params_recursion(self,node:_Node,h_node:_Node,feature_fix):
        """ generate parameters recursively

        Parameters
        ----------
        node : object
                a object form GenNode class
        feature_fix : bool
                a bool parameter show the feature is fixed or not
        """
        if h_node is None:
            if node.depth == self.c_d_max:
                node.h_g = 0
            else:
                node.h_g = self.h_g
            # node.sub_model.set_h_params(**self.sub_h_params)
            node.sub_model = self.SubModel.GenModel(seed=self.rng,**self.sub_h_params)
            if node.depth == self.c_d_max or node.depth == self.c_k or self.rng.random() > self.h_g:  # leaf node
                node.sub_model.gen_params()
                node.leaf = True
            else:  # inner node
                if feature_fix == False or node.k is None:
                    node.k = self.rng.choice(node.k_candidates,
                                             p=self.h_k_prob_vec[node.k_candidates]/self.h_k_prob_vec[node.k_candidates].sum())
                child_k_candidates = copy.copy(node.k_candidates)
                child_k_candidates.remove(node.k)
                node.leaf = False
                for i in range(self.c_num_children):
                    if node.children[i] is None:
                        node.children[i] = _Node(
                            node.depth+1,
                            self.c_num_children,
                            h_g=self.h_g,
                            sub_model=self.SubModel.GenModel(seed=self.rng,**self.sub_h_params),
                            )
                    node.children[i].k_candidates = child_k_candidates
                    self._gen_params_recursion(node.children[i],None,feature_fix)
        else:
            if node.depth == self.c_d_max:
                node.h_g = 0
            else:
                node.h_g = h_node.h_g
            try:
                sub_h_params = h_node.sub_model.get_h_params()
            except:
                sub_h_params = h_node.sub_model.get_hn_params()
            node.sub_model.set_h_params(*sub_h_params.values())
            if node.depth == self.c_d_max or node.depth == self.c_k or self.rng.random() > h_node.h_g:  # leaf node
                node.sub_model.gen_params()
                node.leaf = True
            else:  # inner node
                if feature_fix == False or node.k is None:
                    node.k = self.rng.choice(node.k_candidates,
                                             p=self.h_k_prob_vec[node.k_candidates]/self.h_k_prob_vec[node.k_candidates].sum())
                child_k_candidates = copy.copy(node.k_candidates)
                child_k_candidates.remove(node.k)
                node.leaf = False
                for i in range(self.c_num_children):
                    if node.children[i] is None:
                        node.children[i] = _Node(
                            node.depth+1,
                            self.c_num_children,
                            h_g=self.h_g,
                            sub_model=self.SubModel.GenModel(seed=self.rng,**self.sub_h_params),
                            )
                    node.children[i].k_candidates = child_k_candidates
                    self._gen_params_recursion(node.children[i],h_node.children[i],feature_fix)

    def _gen_params_recursion_tree_fix(self,node:_Node,h_node:_Node,feature_fix):
        """ generate parameters recursively for fixed tree

        Parameters
        ----------
        node : object
                a object form GenNode class
        feature_fix : bool
                a bool parameter show the feature is fixed or not
        """
        if h_node is None:
            if node.depth == self.c_d_max:
                node.h_g = 0
            else:
                node.h_g = self.h_g
            # node.sub_model.set_h_params(**self.sub_h_params)
            node.sub_model = self.SubModel.GenModel(seed=self.rng,**self.sub_h_params)
            if node.leaf:  # leaf node
                node.sub_model.gen_params()
                node.leaf = True
            else:  # inner node
                if feature_fix == False or node.k is None:
                    node.k = self.rng.choice(node.k_candidates,
                                             p=self.h_k_prob_vec[node.k_candidates]/self.h_k_prob_vec[node.k_candidates].sum())
                child_k_candidates = copy.copy(node.k_candidates)
                child_k_candidates.remove(node.k)
                node.leaf = False
                for i in range(self.c_num_children):
                    if node.children[i] is not None:
                        node.children[i].k_candidates = child_k_candidates
                        self._gen_params_recursion_tree_fix(node.children[i],None,feature_fix)
        else:
            if node.depth == self.c_d_max:
                node.h_g = 0
            else:
                node.h_g = h_node.h_g
            try:
                sub_h_params = h_node.sub_model.get_h_params()
            except:
                sub_h_params = h_node.sub_model.get_hn_params()
            node.sub_model.set_h_params(*sub_h_params.values())
            if node.leaf:  # leaf node
                node.sub_model.gen_params()
                node.leaf = True
            else:  # inner node
                if feature_fix == False or node.k is None:
                    node.k = self.rng.choice(node.k_candidates,
                                             p=self.h_k_prob_vec[node.k_candidates]/self.h_k_prob_vec[node.k_candidates].sum())
                child_k_candidates = copy.copy(node.k_candidates)
                child_k_candidates.remove(node.k)
                node.leaf = False
                for i in range(self.c_num_children):
                    if node.children[i] is not None:
                        node.children[i].k_candidates = child_k_candidates
                        self._gen_params_recursion_tree_fix(node.children[i],h_node,feature_fix)

    def _set_params_recursion(self,node:_Node,original_tree_node:_Node):
        """ copy parameters from a fixed tree

        Parameters
        ----------
        node : object
                a object form GenNode class
        original_tree_node : object
                a object form GenNode class
        """
        if original_tree_node.leaf:  # leaf node
            try:
                sub_params = original_tree_node.sub_model.get_params()
                node.sub_model.set_params(**sub_params)
            except:
                try:
                    sub_params = original_tree_node.sub_model.estimate_params(loss='0-1',dict_out=True)
                    node.sub_model.set_params(**sub_params)
                except:
                    sub_params = original_tree_node.sub_model.estimate_params(dict_out=True)
                    node.sub_model.set_params(**sub_params)

            if node.depth == self.c_d_max:
                node.h_g = 0
            node.leaf = True
        else:
            node.k = original_tree_node.k
            child_k_candidates = copy.copy(node.k_candidates)
            child_k_candidates.remove(node.k)
            node.leaf = False
            for i in range(self.c_num_children):
                node.children[i] = _Node(
                    node.depth+1,
                    self.c_num_children,
                    child_k_candidates,
                    self.h_g,
                    sub_model=self.SubModel.GenModel(seed=self.rng,**self.sub_h_params)
                    )
                self._set_params_recursion(node.children[i],original_tree_node.children[i])
    
    def _gen_sample_recursion(self,node:_Node,x):
        """Generate a sample from the stochastic data generative model.

        Parameters
        ----------
        node : object
                a object form GenNode class

        x : numpy ndarray
            1 dimensional array whose elements are 0 or 1.
        """
        if node.leaf:  # leaf node
            try:
                y = node.sub_model.gen_sample(sample_size=1,x=x)
            except:
                y = node.sub_model.gen_sample(sample_size=1)
            return y
        else:
            return self._gen_sample_recursion(node.children[x[node.k]],x)
    
    def _visualize_model_recursion(self,tree_graph,node:_Node,node_id,parent_id,sibling_num,p_v):
        """Visualize the stochastic data generative model and generated samples."""
        tmp_id = node_id
        tmp_p_v = p_v
        
        # add node information
        if node.leaf:
            label_string = 'k=None\\l'
        else:
            label_string = f'k={node.k}\\l'
        label_string += f'h_g={node.h_g:.2f}\\lp_v={tmp_p_v:.2f}\\lsub_params={{'
        if node.leaf:
            sub_params = node.sub_model.get_params()
            for key,value in sub_params.items():
                try:
                    label_string += f'\\l{key}:{value:.2f}'
                except:
                    label_string += f'\\l{key}:{value}'
            label_string += '}'
        else:
            label_string += '\\lNone}'
            
        tree_graph.node(name=f'{tmp_id}',label=label_string,fillcolor=f'{rgb2hex(_CMAP(tmp_p_v))}')
        if tmp_p_v > 0.65:
            tree_graph.node(name=f'{tmp_id}',fontcolor='white')
        
        # add edge information
        if parent_id is not None:
            tree_graph.edge(f'{parent_id}', f'{tmp_id}', label=f'{sibling_num}')
        
        if node.leaf != True:
            for i in range(self.c_num_children):
                node_id = self._visualize_model_recursion(tree_graph,node.children[i],node_id+1,tmp_id,i,tmp_p_v*node.h_g)
        
        return node_id

    def _set_h_g_recursion(self,node:_Node):
        if node.depth == self.c_d_max:
            node.h_g = 0
        else:
            node.h_g = self.h_g
        for i in range(self.c_num_children):
            if node.children[i] is not None:
                self._set_h_g_recursion(node.children[i])

    def _set_sub_h_params_recursion(self,node:_Node):
        # node.sub_model.set_h_params(**self.sub_h_params)
        node.sub_model = self.SubModel.GenModel(seed=self.rng,**self.sub_h_params)
        for i in range(self.c_num_children):
            if node.children[i] is not None:
                self._set_sub_h_params_recursion(node.children[i])

    def _set_h_params_recursion(self,node:_Node,original_tree_node:_Node):
        """ copy parameters from a fixed tree

        Parameters
        ----------
        node : object
                a object from _Node class
        original_tree_node : object
                a object from _Node class
        """
        if original_tree_node is None:
            if node.depth == self.c_d_max:
                node.h_g = 0
            else:
                node.h_g = self.h_g
            # node.sub_model.set_h_params(**self.sub_h_params)
            node.sub_model = self.SubModel.GenModel(seed=self.rng,**self.sub_h_params)
            for i in range(self.c_num_children):
                if node.children[i] is not None:
                    self._set_h_params_recursion(node.children[i],None)
        else:
            if node.depth == self.c_d_max:
                node.h_g = 0
            else:
                node.h_g = original_tree_node.h_g
            try:
                sub_h_params = node.sub_model.get_h_params()
            except:
                sub_h_params = node.sub_model.get_hn_params()
            node.sub_model.set_h_params(*sub_h_params.values())
            if original_tree_node.leaf or node.depth == self.c_d_max:  # leaf node
                node.leaf = True
            else:
                node.k = original_tree_node.k
                child_k_candidates = copy.copy(node.k_candidates)
                child_k_candidates.remove(node.k)
                node.leaf = False
                for i in range(self.c_num_children):
                    if node.children[i] is None:
                        node.children[i] = _Node(
                            node.depth+1,
                            self.c_num_children,
                            child_k_candidates,
                            sub_model=self.SubModel.GenModel(seed=self.rng,**self.sub_h_params),
                            )
                    self._set_h_params_recursion(node.children[i],original_tree_node.children[i])

    def set_h_params(self,
            h_k_prob_vec = None,
            h_g=None,
            sub_h_params=None,
            h_metatree_list=None,
            h_metatree_prob_vec=None
            ):
        """Set the hyperparameters of the prior distribution.

        Parameters
        ----------
        h_k_prob_vec : numpy.ndarray, optional
            A vector of real numbers in :math:`[0, 1]`, 
            by default None
            Sum of its elements must be 1.
        h_g : float, optional
            A real number in :math:`[0, 1]`, by default None
        sub_h_params : dict, optional
            h_params for self.SubModel.GenModel, by default None
        h_metatree_list : list of metatree._Node, optional
            Root nodes of meta-trees, by default None
        h_metatree_prob_vec : numpy.ndarray, optional
            A vector of real numbers in :math:`[0, 1]` 
            that represents prior distribution of h_metatree_list, 
            by default None.
            Sum of its elements must be 1.0.
        """
        if h_k_prob_vec is not None:
            _check.float_vec_sum_1(h_k_prob_vec,'h_k_prob_vec',ParameterFormatError)
            _check.shape_consistency(
                h_k_prob_vec.shape[0],'h_k_prob_vec',
                self.c_k,'self.c_k',
                ParameterFormatError
                )
            self.h_k_prob_vec[:] = h_k_prob_vec

        if h_g is not None:
            self.h_g = _check.float_in_closed01(h_g,'h_g',ParameterFormatError)
            if self.h_metatree_list:
                for h_root in self.h_metatree_list:
                    self._set_h_g_recursion(h_root)

        if sub_h_params is not None:
            self.SubModel.GenModel(seed=self.rng,**sub_h_params)
            self.sub_h_params = copy.deepcopy(sub_h_params)
            if self.h_metatree_list:
                for h_root in self.h_metatree_list:
                    self._set_sub_h_params_recursion(h_root)

        if h_metatree_list is not None:
            if not isinstance(h_metatree_list,list):
                raise(ParameterFormatError(
                    "h_metatree_list must be a list"
                ))
            if h_metatree_list:
                for h_root in h_metatree_list:
                    if type(h_root) is not _Node:
                        raise(ParameterFormatError(
                            "all elements of h_metatree_list must be instances of metatree._Node or empty"
                        ))
            diff = len(h_metatree_list) - len(self.h_metatree_list)
            if diff < 0:
                del self.h_metatree_list[diff:]
            elif diff > 0:
                for i in range(diff):
                    self.h_metatree_list.append(
                        _Node(
                            0,
                            self.c_num_children,
                            list(range(self.c_k)),
                            self.h_g,
                            sub_model=self.SubModel.GenModel(seed=self.rng,**self.sub_h_params),
                            )
                    )
            for i in range(len(self.h_metatree_list)):
                self._set_h_params_recursion(self.h_metatree_list[i],h_metatree_list[i])
            if h_metatree_prob_vec is not None:
                self.h_metatree_prob_vec = np.copy(
                    _check.float_vec_sum_1(
                        h_metatree_prob_vec,
                        'h_metatree_prob_vec',
                        ParameterFormatError
                    )
                )
            else:
                if h_metatree_list:
                    metatree_num = len(self.h_metatree_list)
                    self.h_metatree_prob_vec = np.ones(metatree_num) / metatree_num
                else:
                    self.h_metatree_prob_vec = None
        elif h_metatree_prob_vec is not None:
            self.h_metatree_prob_vec = np.copy(
                _check.float_vec_sum_1(
                    h_metatree_prob_vec,
                    'h_metatree_prob_vec',
                    ParameterFormatError
                )
            )

        if type(self.h_metatree_prob_vec) is np.ndarray:             
            if self.h_metatree_prob_vec.shape[0] != len(self.h_metatree_list):
                raise(ParameterFormatError(
                    "Length of h_metatree_list and dimension of h_metatree_prob_vec must be the same."
                ))
        elif self.h_metatree_prob_vec is None:
            if len(self.h_metatree_list) > 0:
                raise(ParameterFormatError(
                    "Length of h_metatree_list must be zero when self.h_metatree_prob_vec is None."
                ))
        else:
            raise(ParameterFormatError(
                "self.h_metatree_prob_vec must be None or a numpy.ndarray."
            ))

    def get_h_params(self):
        """Get the hyperparameters of the prior distribution.

        Returns
        -------
        hn_params : dict of {str: float, list, dict, numpy.ndarray}
            * ``"h_k_prob_vec"`` : the value of ``self.h_k_prob_vec``
            * ``"h_g"`` : the value of ``self.h_g``
            * ``"sub_h_params"`` : the value of ``self.sub_h_params``
            * ``"h_metatree_list"`` : the value of ``self.h_metatree_list``
            * ``"h_metatree_prob_vec"`` : the value of ``self.h_metatree_prob_vec``
        """
        return {"h_k_prob_vec":self.h_k_prob_vec,
                "h_g":self.h_g, 
                "sub_h_params":self.sub_h_params, 
                "h_metatree_list":self.h_metatree_list,
                "h_metatree_prob_vec":self.h_metatree_prob_vec}
    
    def gen_params(self,feature_fix=False,tree_fix=False):
        """Generate the parameter from the prior distribution.

        The generated vaule is set at ``self.root``.

        Parameters
        ----------
        feature_fix : bool
            If ``True``, feature assignment indices will be fixed, by default ``False``.
        tree_fix : bool
            If ``True``, tree shape will be fixed, by default ``False``.
        """
        if self.h_metatree_list:
            tmp_root = self.rng.choice(self.h_metatree_list,p=self.h_metatree_prob_vec)
            if tree_fix:
                self._gen_params_recursion_tree_fix(self.root,tmp_root,feature_fix)
            else:
                self._gen_params_recursion(self.root,tmp_root,feature_fix)
        else:
            if tree_fix:
                self._gen_params_recursion_tree_fix(self.root,None,feature_fix)
            else:
                self._gen_params_recursion(self.root,None,feature_fix)
    
    def set_params(self,root=None):
        """Set the parameter of the sthocastic data generative model.

        Parameters
        ----------
        root : metatree._Node, optional
            A root node of a meta-tree, by default None.
        """
        if root is not None:
            if type(root) is not _Node:
                raise(ParameterFormatError(
                    "root must be an instance of metatree._Node"
                ))
            self.root = _Node(
                0,
                self.c_num_children,
                list(range(self.c_k)),
                self.h_g,
                sub_model=self.SubModel.GenModel(seed=self.rng,**self.sub_h_params),
                leaf=True
                )
            self._set_params_recursion(self.root,root)

    def get_params(self):
        """Get the parameter of the sthocastic data generative model.

        Returns
        -------
        params : dict of {str:float}
            * ``"root"`` : The value of ``self.root``.
        """
        return {"root":self.root}

    def gen_sample(self,sample_size=None,x=None):
        """Generate a sample from the stochastic data generative model.

        Parameters
        ----------
        sample_size : int
            A positive integer
        x : numpy ndarray, optional
            2 dimensional array whose size is ``(sammple_size,c_k)``, by default None.
            Each element x[i,j] must satisfy 0 <= x[i,j] < c_num_children.

        Returns
        -------
        x : numpy ndarray
            2 dimensional array whose size is ``(sammple_size,c_k)``.
            Each element x[i,j] satisfies 0 <= x[i,j] < c_num_children.
        y : numpy ndarray
            1 dimensional array whose size is ``sammple_size``.
        """
        if x is not None:
            _check.int_vecs(x,'x',DataFormatError)
            _check.shape_consistency(
                x.shape[-1],'x.shape[-1]',
                self.c_k,'self.c_k',
                ParameterFormatError
                )
            if x.max() >= self.c_num_children:
                raise(DataFormatError(f"x.max() must smaller than c_num_children:{self.c_num_children}"))
            x = x.reshape(-1,self.c_k)
            sample_size = x.shape[0]
        elif sample_size is not None:
            _check.pos_int(sample_size,'sample_size',DataFormatError)
            x = self.rng.choice(self.c_num_children,(sample_size,self.c_k))
        else:
            raise(DataFormatError("Either of the sample_size and the x must be given as a input."))
        
        if self.SubModel in DISCRETE_MODELS:
            y = np.empty(sample_size,dtype=int)
        elif self.SubModel in CONTINUOUS_MODELS:
            y = np.empty(sample_size,dtype=float)
        
        for i in range(sample_size):
            y[i] = self._gen_sample_recursion(self.root,x[i])

        return x,y
        
    def save_sample(self,filename,sample_size,x=None):
        """Save the generated sample as NumPy ``.npz`` format.

        It is saved as a NpzFile with keyword: \"x\".

        Parameters
        ----------
        filename : str
            The filename to which the sample is saved.
            ``.npz`` will be appended if it isn't there.
        sample_size : int
            A positive integer
        x : numpy ndarray, optional
            2 dimensional array whose size is ``(sammple_size,c_k)``, by default None.
            Each element x[i,j] must satisfy 0 <= x[i,j] < c_num_children.
        
        See Also
        --------
        numpy.savez_compressed
        """
        x,y = self.gen_sample(sample_size,x)
        np.savez_compressed(filename,x=x,y=y)

    def visualize_model(self,filename=None,format=None,sample_size=10):
        """Visualize the stochastic data generative model and generated samples.

        Parameters
        ----------
        filename : str, optional
            Filename for saving the figure, by default ``None``
        format : str, optional
            Rendering output format (``\"pdf\"``, ``\"png\"``, ...).
        sample_size : int, optional
            A positive integer, by default 10

        Examples
        --------
        >>> from bayesml import metatree
        >>> model = metatree.GenModel(c_k=3,h_g=0.75)
        >>> model.visualize_model()
        [[1 1 0]
         [1 0 0]
         [0 0 0]
         [1 0 0]
         [1 1 1]
         [0 0 1]
         [1 1 1]
         [1 0 1]
         [0 1 1]
         [0 1 0]]
        [0 1 0 1 0 0 0 1 0 0]

        .. image:: ./images/metatree_example.png

        See Also
        --------
        graphviz.Digraph
        """
        _check.pos_int(sample_size,'sample_size',DataFormatError)

        try:
            import graphviz
            tree_graph = graphviz.Digraph(filename=filename,format=format)
            tree_graph.attr("node",shape="box",fontname="helvetica",style="rounded,filled")
            self._visualize_model_recursion(tree_graph, self.root, 0, None, None, 1.0)        
            # Can we show the image on the console without saving the file?
            tree_graph.view()
        except ImportError as e:
            print(e)
        except graphviz.CalledProcessError as e:
            print(e)
        # The following visualization should be modified. Jitter plot may be useful．
        x,y = self.gen_sample(sample_size)
        print(x)
        print(y)

class LearnModel(base.Posterior,base.PredictiveMixin):
    """The posterior distribution and the predictive distribution.

    Parameters
    ----------
    c_k : int
        A positive integer
    c_d_max : int, optional
        A positive integer, by default 10
    c_num_children : int, optional
        A positive integer, by default 2
    SubModel : class, optional
        bernoulli, poisson, normal, or exponential, 
        by default bernoulli
    h0_k_prob_vec : numpy.ndarray, optional
        A vector of real numbers in :math:`[0, 1]`, 
        by default [1/c_k, 1/c_k, ... , 1/c_k]
        Sum of its elements must be 1.0.
    h0_g : float, optional
        A real number in :math:`[0, 1]`, by default 0.5
    sub_h0_params : dict, optional
        h0_params for self.SubModel, by default {}
    h0_metatree_list : list of metatree._Node, optional
        Root nodes of meta-trees, by default []
    h0_metatree_prob_vec : numpy.ndarray, optional
        A vector of real numbers in :math:`[0, 1]` 
        that represents prior distribution of h0_metatree_list, 
        by default uniform distribution
        Sum of its elements must be 1.0.

    Attributes
    ----------
    hn_k_prob_vec : numpy.ndarray
        A vector of real numbers in :math:`[0, 1]`. 
        Sum of its elements is 1.
    hn_g : float
        A real number in :math:`[0, 1]`
    sub_hn_params : dict
        hn_params for self.SubModel
    hn_metatree_list : list of metatree._Node
        Root nodes of meta-trees
    hn_metatree_prob_vec : numpy.ndarray
        A vector of real numbers in :math:`[0, 1]` 
        that represents prior distribution of h0_metatree_list.
        Sum of its elements is 1.0.
    """
    def __init__(
            self,
            c_k,
            c_d_max=10,
            c_num_children=2,
            *,
            SubModel=bernoulli,
            h0_k_prob_vec = None,
            h0_g=0.5,
            sub_h0_params={},
            h0_metatree_list=[],
            h0_metatree_prob_vec=None
            ):
        # constants
        self.c_d_max = _check.pos_int(c_d_max,'c_d_max',ParameterFormatError)
        self.c_num_children = _check.pos_int(c_num_children,'c_num_children',ParameterFormatError)
        self.c_k = _check.pos_int(c_k,'c_k',ParameterFormatError)
        if SubModel not in MODELS:
            raise(ParameterFormatError(
                "SubModel must be bernoulli, "
                +"poisson, normal, or exponential."
            ))
        self.SubModel = SubModel

        # h0_params
        self.h0_k_prob_vec = np.ones(self.c_k) / self.c_k
        self.h0_g = 0.5
        self.sub_h0_params = {}
        self.h0_metatree_list = []
        self.h0_metatree_prob_vec = None

        # hn_params
        self.hn_k_prob_vec = np.ones(self.c_k) / self.c_k
        self.hn_g = 0.5
        self.sub_hn_params = {}
        self.hn_metatree_list = []
        self.hn_metatree_prob_vec = None

        self._tmp_x = np.zeros(self.c_k,dtype=int)

        self.set_h0_params(
            h0_k_prob_vec,
            h0_g,
            sub_h0_params,
            h0_metatree_list,
            h0_metatree_prob_vec,
        )

    def _set_h0_g_recursion(self,node:_Node):
        if node.depth == self.c_d_max:
            node.h_g = 0
        else:
            node.h_g = self.h0_g
        for i in range(self.c_num_children):
            if node.children[i] is not None:
                self._set_h0_g_recursion(node.children[i])

    def _set_sub_h0_params_recursion(self,node:_Node):
        # node.sub_model.set_h0_params(**self.sub_h0_params)
        node.sub_model = self.SubModel.LearnModel(**self.sub_h0_params)
        for i in range(self.c_num_children):
            if node.children[i] is not None:
                self._set_sub_h0_params_recursion(node.children[i])

    def _set_h0_params_recursion(self,node:_Node,original_tree_node:_Node):
        """ copy parameters from a fixed tree

        Parameters
        ----------
        node : object
                a object from _Node class
        original_tree_node : object
                a object from _Node class
        """
        if original_tree_node is None:
            if node.depth == self.c_d_max:
                node.h_g = 0
            else:
                node.h_g = self.h0_g
            # node.sub_model.set_h0_params(**self.sub_h0_params)
            node.sub_model = self.SubModel.LearnModel(**self.sub_h0_params)
            for i in range(self.c_num_children):
                if node.children[i] is not None:
                    self._set_h0_params_recursion(node.children[i],None)
        else:
            if node.depth == self.c_d_max:
                node.h_g = 0
            else:
                node.h_g = original_tree_node.h_g
            try:
                sub_h0_params = node.sub_model.get_h_params()
            except:
                sub_h0_params = node.sub_model.get_h0_params()
            node.sub_model.set_h0_params(*sub_h0_params.values())
            if original_tree_node.leaf or node.depth == self.c_d_max:  # leaf node
                node.leaf = True
            else:
                node.k = original_tree_node.k
                child_k_candidates = copy.copy(node.k_candidates)
                child_k_candidates.remove(node.k)
                node.leaf = False
                for i in range(self.c_num_children):
                    if node.children[i] is None:
                        node.children[i] = _Node(
                            node.depth+1,
                            self.c_num_children,
                            child_k_candidates,
                            sub_model=self.SubModel.LearnModel(**self.sub_h0_params),
                            )
                    self._set_h0_params_recursion(node.children[i],original_tree_node.children[i])

    def _set_hn_g_recursion(self,node:_Node):
        if node.depth == self.c_d_max:
            node.h_g = 0
        else:
            node.h_g = self.hn_g
        for i in range(self.c_num_children):
            if node.children[i] is not None:
                self._set_hn_g_recursion(node.children[i])

    def _set_sub_hn_params_recursion(self,node:_Node):
        # node.sub_model.set_hn_params(**self.sub_hn_params)
        node.sub_model = self.SubModel.LearnModel(**self.sub_hn_params)
        for i in range(self.c_num_children):
            if node.children[i] is not None:
                self._set_sub_hn_params_recursion(node.children[i])

    def _set_hn_params_recursion(self,node:_Node,original_tree_node:_Node):
        """ copy parameters from a fixed tree

        Parameters
        ----------
        node : object
                a object from _Node class
        original_tree_node : object
                a object from _Node class
        """
        if original_tree_node is None:
            if node.depth == self.c_d_max:
                node.h_g = 0
            else:
                node.h_g = self.hn_g
            # node.sub_model.set_hn_params(**self.sub_hn_params)
            node.sub_model = self.SubModel.LearnModel(**self.sub_hn_params)
            for i in range(self.c_num_children):
                if node.children[i] is not None:
                    self._set_hn_params_recursion(node.children[i],None)
        else:
            if node.depth == self.c_d_max:
                node.h_g = 0
            else:
                node.h_g = original_tree_node.h_g
            try:
                sub_hn_params = node.sub_model.get_h_params()
            except:
                sub_hn_params = node.sub_model.get_hn_params()
            node.sub_model.set_hn_params(*sub_hn_params.values())
            if original_tree_node.leaf or node.depth == self.c_d_max:  # leaf node
                node.leaf = True
            else:
                node.k = original_tree_node.k
                child_k_candidates = copy.copy(node.k_candidates)
                child_k_candidates.remove(node.k)
                node.leaf = False
                for i in range(self.c_num_children):
                    if node.children[i] is None:
                        node.children[i] = _Node(
                            node.depth+1,
                            self.c_num_children,
                            child_k_candidates,
                            sub_model=self.SubModel.LearnModel(**self.sub_hn_params),
                            )
                    self._set_hn_params_recursion(node.children[i],original_tree_node.children[i])

    def set_h0_params(self,
        h0_k_prob_vec = None,
        h0_g=None,
        sub_h0_params=None,
        h0_metatree_list=None,
        h0_metatree_prob_vec=None
        ):
        """Set the hyperparameters of the prior distribution.

        Parameters
        ----------
        h0_k_prob_vec : numpy.ndarray, optional
            A vector of real numbers in :math:`[0, 1]`, 
            by default None
            Sum of its elements must be 1.
        h0_g : float, optional
            A real number in :math:`[0, 1]`, by default None
        sub_h0_params : dict, optional
            h0_params for self.SubModel.LearnModel, by default None
        h0_metatree_list : list of metatree._Node, optional
            Root nodes of meta-trees, by default None
        h0_metatree_prob_vec : numpy.ndarray, optional
            A vector of real numbers in :math:`[0, 1]` 
            that represents prior distribution of h0_metatree_list, 
            by default None.
            Sum of its elements must be 1.0.
        """
        if h0_k_prob_vec is not None:
            _check.float_vec_sum_1(h0_k_prob_vec,'h0_k_prob_vec',ParameterFormatError)
            _check.shape_consistency(
                h0_k_prob_vec.shape[0],'h0_k_prob_vec',
                self.c_k,'self.c_k',
                ParameterFormatError
                )
            self.h0_k_prob_vec[:] = h0_k_prob_vec

        if h0_g is not None:
            self.h0_g = _check.float_in_closed01(h0_g,'h0_g',ParameterFormatError)
            if self.h0_metatree_list:
                for h0_root in self.h0_metatree_list:
                    self._set_h0_g_recursion(h0_root)

        if sub_h0_params is not None:
            self.SubModel.LearnModel(**sub_h0_params)
            self.sub_h0_params = copy.deepcopy(sub_h0_params)
            if self.h0_metatree_list:
                for h0_root in self.h0_metatree_list:
                    self._set_sub_h0_params_recursion(h0_root)

        if h0_metatree_list is not None:
            if not isinstance(h0_metatree_list,list):
                raise(ParameterFormatError(
                    "h0_metatree_list must be a list"
                ))
            if h0_metatree_list:
                for h0_root in h0_metatree_list:
                    if type(h0_root) is not _Node:
                        raise(ParameterFormatError(
                            "all elements of h0_metatree_list must be instances of metatree._Node or empty"
                        ))
            diff = len(h0_metatree_list) - len(self.h0_metatree_list)
            if diff < 0:
                del self.h0_metatree_list[diff:]
            elif diff > 0:
                for i in range(diff):
                    self.h0_metatree_list.append(
                        _Node(
                            0,
                            self.c_num_children,
                            list(range(self.c_k)),
                            self.h0_g,
                            sub_model=self.SubModel.LearnModel(**self.sub_h0_params),
                            )
                    )
            for i in range(len(self.h0_metatree_list)):
                self._set_h0_params_recursion(self.h0_metatree_list[i],h0_metatree_list[i])
            if h0_metatree_prob_vec is not None:
                self.h0_metatree_prob_vec = np.copy(
                    _check.float_vec_sum_1(
                        h0_metatree_prob_vec,
                        'h0_metatree_prob_vec',
                        ParameterFormatError
                    )
                )
            else:
                if h0_metatree_list:
                    metatree_num = len(self.h0_metatree_list)
                    self.h0_metatree_prob_vec = np.ones(metatree_num) / metatree_num
                else:
                    self.h0_metatree_prob_vec = None
        elif h0_metatree_prob_vec is not None:
            self.h0_metatree_prob_vec = np.copy(
                _check.float_vec_sum_1(
                    h0_metatree_prob_vec,
                    'h0_metatree_prob_vec',
                    ParameterFormatError
                )
            )

        if type(self.h0_metatree_prob_vec) is np.ndarray:             
            if self.h0_metatree_prob_vec.shape[0] != len(self.h0_metatree_list):
                raise(ParameterFormatError(
                    "Length of h0_metatree_list and dimension of h0_metatree_prob_vec must be the same."
                ))
        elif self.h0_metatree_prob_vec is None:
            if len(self.h0_metatree_list) > 0:
                raise(ParameterFormatError(
                    "Length of h0_metatree_list must be zero when self.h0_metatree_prob_vec is None."
                ))
        else:
            raise(ParameterFormatError(
                "self.h0_metatree_prob_vec must be None or a numpy.ndarray."
            ))

        self.reset_hn_params()

    def get_h0_params(self):
        """Get the hyperparameters of the prior distribution.

        Returns
        -------
        h0_params : dict of {str: float, list, dict, numpy.ndarray}
            * ``"h0_k_prob_vec"`` : the value of ``self.h0_k_prob_vec``
            * ``"h0_g"`` : the value of ``self.h0_g``
            * ``"sub_h0_params"`` : the value of ``self.sub_h0_params``
            * ``"h0_metatree_list"`` : the value of ``self.h0_metatree_list``
            * ``"h0_metatree_prob_vec"`` : the value of ``self.h0_metatree_prob_vec``
        """
        return {"h0_k_prob_vec":self.h0_k_prob_vec,
                "h0_g":self.h0_g, 
                "sub_h0_params":self.sub_h0_params, 
                "h0_metatree_list":self.h0_metatree_list,
                "h0_metatree_prob_vec":self.h0_metatree_prob_vec}
    
    def set_hn_params(self,
        hn_k_prob_vec = None,
        hn_g=None,
        sub_hn_params=None,
        hn_metatree_list=None,
        hn_metatree_prob_vec=None
        ):
        """Set the hyperparameters of the posterior distribution.

        Parameters
        ----------
        hn_k_prob_vec : numpy.ndarray, optional
            A vector of real numbers in :math:`[0, 1]`, 
            by default None
            Sum of its elements must be 1.
        hn_g : float, optional
            A real number in :math:`[0, 1]`, by default None
        sub_hn_params : dict, optional
            hn_params for self.SubModel.LearnModel, by default None
        hn_metatree_list : list of metatree._Node, optional
            Root nodes of meta-trees, by default None
        hn_metatree_prob_vec : numpy.ndarray, optional
            A vector of real numbers in :math:`[0, 1]` 
            that represents prior distribution of hn_metatree_list, 
            by default None.
            Sum of its elements must be 1.0.
        """
        if hn_k_prob_vec is not None:
            _check.float_vec_sum_1(hn_k_prob_vec,'hn_k_prob_vec',ParameterFormatError)
            _check.shape_consistency(
                hn_k_prob_vec.shape[0],'hn_k_prob_vec',
                self.c_k,'self.c_k',
                ParameterFormatError
                )
            self.hn_k_prob_vec[:] = hn_k_prob_vec

        if hn_g is not None:
            self.hn_g = _check.float_in_closed01(hn_g,'hn_g',ParameterFormatError)
            if self.hn_metatree_list:
                for hn_root in self.hn_metatree_list:
                    self._set_hn_g_recursion(hn_root)

        if sub_hn_params is not None:
            self.SubModel.LearnModel(**sub_hn_params)
            self.sub_hn_params = copy.deepcopy(sub_hn_params)
            if self.hn_metatree_list:
                for hn_root in self.hn_metatree_list:
                    self._set_sub_hn_params_recursion(hn_root)

        if hn_metatree_list is not None:
            if not isinstance(hn_metatree_list,list):
                raise(ParameterFormatError(
                    "hn_metatree_list must be a list"
                ))
            if hn_metatree_list:
                for hn_root in hn_metatree_list:
                    if type(hn_root) is not _Node:
                        raise(ParameterFormatError(
                            "all elements of hn_metatree_list must be instances of metatree._Node or empty"
                        ))
            diff = len(hn_metatree_list) - len(self.hn_metatree_list)
            if diff < 0:
                del self.hn_metatree_list[diff:]
            elif diff > 0:
                for i in range(diff):
                    self.hn_metatree_list.append(
                        _Node(
                            0,
                            self.c_num_children,
                            list(range(self.c_k)),
                            self.hn_g,
                            sub_model=self.SubModel.LearnModel(**self.sub_hn_params),
                            )
                    )
            for i in range(len(self.hn_metatree_list)):
                self._set_hn_params_recursion(self.hn_metatree_list[i],hn_metatree_list[i])
            if hn_metatree_prob_vec is not None:
                self.hn_metatree_prob_vec = np.copy(
                    _check.float_vec_sum_1(
                        hn_metatree_prob_vec,
                        'hn_metatree_prob_vec',
                        ParameterFormatError
                    )
                )
            else:
                if hn_metatree_list:
                    metatree_num = len(self.hn_metatree_list)
                    self.hn_metatree_prob_vec = np.ones(metatree_num) / metatree_num
                else:
                    self.hn_metatree_prob_vec = None
        elif hn_metatree_prob_vec is not None:
            self.hn_metatree_prob_vec = np.copy(
                _check.float_vec_sum_1(
                    hn_metatree_prob_vec,
                    'hn_metatree_prob_vec',
                    ParameterFormatError
                )
            )

        if type(self.hn_metatree_prob_vec) is np.ndarray:             
            if self.hn_metatree_prob_vec.shape[0] != len(self.hn_metatree_list):
                raise(ParameterFormatError(
                    "Length of hn_metatree_list and dimension of hn_metatree_prob_vec must be the same."
                ))
        elif self.hn_metatree_prob_vec is None:
            if len(self.hn_metatree_list) > 0:
                raise(ParameterFormatError(
                    "Length of hn_metatree_list must be zero when self.hn_metatree_prob_vec is None."
                ))
        else:
            raise(ParameterFormatError(
                "self.hn_metatree_prob_vec must be None or a numpy.ndarray."
            ))

        self.calc_pred_dist(np.zeros(self.c_k,dtype=int))

    def get_hn_params(self):
        """Get the hyperparameters of the posterior distribution.

        Returns
        -------
        hn_params : dict of {str: float, list, dict, numpy.ndarray}
            * ``"hn_k_prob_vec"`` : the value of ``self.hn_k_prob_vec``
            * ``"hn_g"`` : the value of ``self.hn_g``
            * ``"sub_hn_params"`` : the value of ``self.sub_hn_params``
            * ``"hn_metatree_list"`` : the value of ``self.hn_metatree_list``
            * ``"hn_metatree_prob_vec"`` : the value of ``self.hn_metatree_prob_vec``
        """
        return {"hn_k_prob_vec":self.hn_k_prob_vec,
                "hn_g":self.hn_g, 
                "sub_hn_params":self.sub_hn_params, 
                "hn_metatree_list":self.hn_metatree_list,
                "hn_metatree_prob_vec":self.hn_metatree_prob_vec}
    
    def _copy_tree_from_sklearn_tree(self,new_node:_Node, original_tree,node_id):
        if original_tree.children_left[node_id] != sklearn_tree._tree.TREE_LEAF:  # inner node
            new_node.k = original_tree.feature[node_id]
            child_k_candidates = copy.copy(new_node.k_candidates)
            child_k_candidates.remove(new_node.k)
            new_node.children[0] = _Node(
                new_node.depth+1,
                2,
                child_k_candidates,
                h_g=self.h0_g,
                sub_model=self.SubModel.LearnModel(**self.sub_h0_params),
                )
            self._copy_tree_from_sklearn_tree(new_node.children[0],original_tree,original_tree.children_left[node_id])
            new_node.children[1] = _Node(
                new_node.depth+1,
                2,
                child_k_candidates,
                h_g=self.h0_g,
                sub_model=self.SubModel.LearnModel(**self.sub_h0_params),
                )
            self._copy_tree_from_sklearn_tree(new_node.children[1],original_tree,original_tree.children_right[node_id])
        else:
            new_node.h_g = 0.0
            new_node.leaf = True

    def _update_posterior_leaf(self,node:_Node,x,y):
            try:
                node.sub_model.calc_pred_dist(x)
            except:
                node.sub_model.calc_pred_dist()
            pred_dist = node.sub_model.make_prediction(loss='KL') # Futurework: direct method to get marginal likelihood is better

            try:
                node.sub_model.update_posterior(x,y)
            except:
                node.sub_model.update_posterior(y)

            if type(pred_dist) is np.ndarray:
                return pred_dist[y]
            try:
                return pred_dist.pdf(y)
            except:
                return pred_dist.pmf(y)

    def _update_posterior_recursion(self,node:_Node,x,y):
        if node.leaf == False:  # inner node
            tmp1 = self._update_posterior_recursion(node.children[x[node.k]],x,y)
            tmp2 = (1 - node.h_g) * self._update_posterior_leaf(node,x,y) + node.h_g * tmp1
            node.h_g = node.h_g * tmp1 / tmp2
            return tmp2
        else:  # leaf node
            return self._update_posterior_leaf(node,x,y)

    def _compare_metatree_recursion(self,node1:_Node,node2:_Node):
        if node1.leaf == True and node2.leaf == True:
            return True
        elif node1.k == node2.k:
            for i in range(self.c_num_children):
                if self._compare_metatree_recursion(node1.children[i],node2.children[i]) == False:
                    return False
            return True
        else:
            return False
    
    def _marge_metatrees(self,metatree_list,metatree_prob_vec):
        num_metatrees = len(metatree_list)
        for i in range(num_metatrees):
            for j in range(i+1,num_metatrees):
                if self._compare_metatree_recursion(metatree_list[i],metatree_list[j]):
                    metatree_list[i] = None
                    metatree_prob_vec[j] += metatree_prob_vec[i]
                    metatree_prob_vec[i] = -1
                    break
        metatree_list = [tmp for tmp in metatree_list if tmp != None]
        metatree_prob_vec = metatree_prob_vec[metatree_prob_vec > -0.5]
        return metatree_list,metatree_prob_vec

    def _MTRF(self,x,y,n_estimators=100,**kwargs):
        """make metatrees

        Parameters
        ----------
        x : numpy ndarray
            values of explanatory variables whose dtype is int
        y : numpy ndarray
            values of objective variable whose dtype may be int or float
        n_estimators : int, optional
            number of trees in sklearn.RandomForestClassifier, by default 100

        Returns
        -------
        metatree_list : list of metatree._Node
            Each element is a root node of metatree.
        metatree_prob_vec : numpy ndarray
        """
        if self.c_num_children != 2:
            raise(ParameterFormatError("MTRF is supported only when c_num_children == 2."))
        if self.SubModel in DISCRETE_MODELS:
            randomforest = RandomForestClassifier(n_estimators=n_estimators,max_depth=self.c_d_max,**kwargs)
        if self.SubModel in CONTINUOUS_MODELS:
            randomforest = RandomForestRegressor(n_estimators=n_estimators,max_depth=self.c_d_max,**kwargs)
        randomforest.fit(x,y)
        tmp_metatree_list = [_Node(0,2,list(range(self.c_k)),self.hn_g,sub_model=self.SubModel.LearnModel(**self.sub_hn_params)) for i in range(n_estimators)]
        tmp_metatree_prob_vec = np.ones(n_estimators) / n_estimators
        for i in range(n_estimators):
            self._copy_tree_from_sklearn_tree(tmp_metatree_list[i],randomforest.estimators_[i].tree_, 0)

        tmp_metatree_list,tmp_metatree_prob_vec = self._marge_metatrees(tmp_metatree_list,tmp_metatree_prob_vec)

        log_metatree_posteriors = np.log(tmp_metatree_prob_vec)
        for i,metatree in enumerate(tmp_metatree_list):
            for j in range(x.shape[0]):
                log_metatree_posteriors[i] += np.log(self._update_posterior_recursion(metatree,x[j],y[j]))
        tmp_metatree_prob_vec[:] = np.exp(log_metatree_posteriors - log_metatree_posteriors.max())
        tmp_metatree_prob_vec[:] /= tmp_metatree_prob_vec.sum()
        return tmp_metatree_list,tmp_metatree_prob_vec

    def _given_MT(self,x,y):
        """make metatrees

        Parameters
        ----------
        x : numpy ndarray
            values of explanatory variables whose dtype is int
        y : numpy ndarray
            values of objective variable whose dtype may be int or float

        Returns
        -------
        metatree_list : list of metatree._Node
            Each element is a root node of metatree.
        metatree_prob_vec : numpy ndarray
        """
        if not self.hn_metatree_list:
            raise(ParameterFormatError("given_MT is supported only when len(self.hn_metatree_list) > 0."))
        log_metatree_posteriors = np.log(self.hn_metatree_prob_vec)
        for i,metatree in enumerate(self.hn_metatree_list):
            for j in range(x.shape[0]):
                log_metatree_posteriors[i] += np.log(self._update_posterior_recursion(metatree,x[j],y[j]))
        self.hn_metatree_prob_vec[:] = np.exp(log_metatree_posteriors - log_metatree_posteriors.max())
        self.hn_metatree_prob_vec[:] /= self.hn_metatree_prob_vec.sum()
        return self.hn_metatree_list,self.hn_metatree_prob_vec

    def update_posterior(self,x,y,alg_type='MTRF',**kwargs):
        """Update the hyperparameters of the posterior distribution using traning data.

        Parameters
        ----------
        x : numpy ndarray
            values of explanatory variables whose dtype is int
        y : numpy ndarray
            values of objective variable whose dtype may be int or float
        alg_type : {'MTRF', 'given_MT'}, optional
            type of algorithm, by default 'MTRF'
        **kwargs : dict, optional
            optional parameters of algorithms, by default {}
        """
        _check.nonneg_int_vecs(x,'x',DataFormatError)
        if x.shape[-1] != self.c_k:
            raise(DataFormatError(f"x.shape[-1] must equal to c_k:{self.c_k}"))
        if x.max() >= self.c_num_children:
            raise(DataFormatError(f"x.max() must smaller than c_num_children:{self.c_num_children}"))
                
        if type(y) is np.ndarray:
            if x.shape[:-1] != y.shape: 
                raise(DataFormatError(f"x.shape[:-1] and y.shape must be same."))
        elif x.shape[:-1] != ():
            raise(DataFormatError(f"If y is a scaler, x.shape[:-1] must be the empty tuple ()."))

        x = x.reshape(-1,self.c_k)
        y = np.ravel(y)

        if alg_type == 'MTRF':
            self.hn_metatree_list, self.hn_metatree_prob_vec = self._MTRF(x,y,**kwargs)
        elif alg_type == 'given_MT':
            self.hn_metatree_list, self.hn_metatree_prob_vec = self._given_MT(x,y)

    def _map_recursion_add_nodes(self,node:_Node):
        if node.depth == self.c_d_max or node.depth == self.c_k:  # leaf node
            node.h_g = 0.0
            node.leaf = True
            node.map_leaf = True
        else:  # inner node
            node.k = node.k_candidates[0]
            child_k_candidates = copy.copy(node.k_candidates)
            child_k_candidates.remove(node.k)
            for i in range(self.c_num_children):
                node.children[i] = _Node(
                    node.depth+1,
                    self.c_num_children,
                    child_k_candidates,
                    self.hn_g,
                    sub_model=self.SubModel.LearnModel(**self.sub_h0_params)
                    )
                self._map_recursion_add_nodes(node.children[i])

    def _map_recursion(self,node:_Node):
        if node.leaf:
            if node.depth == self.c_d_max or node.depth == self.c_k:
                node.map_leaf = True
                return 1.0
            elif 1.0 - self.hn_g > self.hn_g ** ((self.c_num_children ** (self.c_d_max - node.depth) - 1)/(self.c_num_children-1)):
                node.map_leaf = True
                return 1.0 - self.hn_g
            else:
                self._map_recursion_add_nodes(node)
                return self.hn_g ** ((self.c_num_children ** (self.c_d_max - node.depth) - 1)/(self.c_num_children-1))
        else:
            tmp1 = 1.0-node.h_g
            tmp_vec = np.empty(self.c_num_children)
            for i in range(self.c_num_children):
                tmp_vec[i] = self._map_recursion(node.children[i])
            if tmp1 > node.h_g*tmp_vec.prod():
                node.map_leaf = True
                return tmp1
            else:
                node.map_leaf = False
                return node.h_g*tmp_vec.prod()

    def _copy_map_tree_recursion(self,copyed_node:_Node,original_node:_Node):
        copyed_node.h_g = original_node.h_g
        if original_node.map_leaf == False:
            copyed_node.k = original_node.k
            child_k_candidates = copy.copy(copyed_node.k_candidates)
            child_k_candidates.remove(copyed_node.k)
            for i in range(self.c_num_children):
                copyed_node.children[i] = _Node(
                    copyed_node.depth+1,
                    self.c_num_children,
                    child_k_candidates,
                    )
                self._copy_map_tree_recursion(copyed_node.children[i],original_node.children[i])
        else:
            copyed_node.sub_model = copy.deepcopy(original_node.sub_model)
            copyed_node.leaf = True

    def estimate_params(self,loss="0-1",visualize=True,filename=None,format=None):
        """Estimate the parameter under the given criterion.

        Parameters
        ----------
        loss : str, optional
            Loss function underlying the Bayes risk function, by default ``\"0-1\"``.
            This function supports only ``\"0-1\"``.
        visualize : bool, optional
            If ``True``, the estimated metatree will be visualized, by default ``True``.
            This visualization requires ``graphviz``.
        filename : str, optional
            Filename for saving the figure, by default ``None``
        format : str, optional
            Rendering output format (``\"pdf\"``, ``\"png\"``, ...).


        Returns
        -------
        map_root : metatree._Node
            The root node of the estimated meta-tree 
            that also contains the estimated parameters in each node.

        See Also
        --------
        graphviz.Digraph

        Warnings
        --------
        Multiple metatrees can represent equivalent model classes. 
        This function does not take such duplication into account.
        """

        if loss == "0-1":
            map_index = 0
            map_prob = 0.0
            for i,metatree in enumerate(self.hn_metatree_list):
                prob = self.hn_metatree_prob_vec[i] * self._map_recursion(metatree)
                if prob > map_prob:
                    map_index = i
                    map_prob = prob
            map_root = _Node(0,self.c_num_children,list(range(self.c_k)))
            self._copy_map_tree_recursion(map_root,self.hn_metatree_list[map_index])
            if visualize:
                import graphviz
                tree_graph = graphviz.Digraph(filename=filename,format=format)
                tree_graph.attr("node",shape="box",fontname="helvetica",style="rounded,filled")
                self._visualize_model_recursion(tree_graph, map_root, 0, None, None, 1.0)
                tree_graph.view()
            return {'root':map_root}
        else:
            raise(CriteriaError("Unsupported loss function! "
                                +"This function supports only \"0-1\"."))
    
    def _visualize_model_recursion(self,tree_graph,node:_Node,node_id,parent_id,sibling_num,p_v):
        tmp_id = node_id
        tmp_p_v = p_v
        
        # add node information
        if node.leaf:
            label_string = 'k=None\\l'
        else:
            label_string = f'k={node.k}\\l'
        label_string += f'hn_g={node.h_g:.2f}\\lp_v={tmp_p_v:.2f}\\lsub_params={{'
        if node.sub_model is not None:
            try:
                sub_params = node.sub_model.estimate_params(loss='0-1',dict_out=True)
            except:
                sub_params = node.sub_model.estimate_params(dict_out=True)
            
            for key,value in sub_params.items():
                try:
                    label_string += f'\\l{key}:{value:.2f}'
                except:
                    label_string += f'\\l{key}:{value}'
            label_string += '}'
        else:
            label_string += '\\lNone}'

        tree_graph.node(name=f'{tmp_id}',label=label_string,fillcolor=f'{rgb2hex(_CMAP(tmp_p_v))}')
        if tmp_p_v > 0.65:
            tree_graph.node(name=f'{tmp_id}',fontcolor='white')
        
        # add edge information
        if parent_id is not None:
            tree_graph.edge(f'{parent_id}', f'{tmp_id}', label=f'{sibling_num}')
        
        if node.leaf != True:
            for i in range(self.c_num_children):
                node_id = self._visualize_model_recursion(tree_graph,node.children[i],node_id+1,tmp_id,i,tmp_p_v*node.h_g)
        
        return node_id

    def _visualize_model_recursion_none(self,tree_graph,depth,k_candidates,node_id,parent_id,sibling_num,p_v):
        tmp_id = node_id
        tmp_p_v = p_v
        
        # add node information
        if depth == self.c_d_max or depth == self.c_k:
            label_string = 'k=None\\l'
        else:
            k = k_candidates[self.hn_k_prob_vec[k_candidates].argmax()]
            child_k_candidates = copy.copy(k_candidates)
            child_k_candidates.remove(k)
            label_string = f'k={k}\\l'
        label_string += f'hn_g={self.hn_g:.2f}\\lp_v={tmp_p_v:.2f}\\lsub_params={{'

        sub_model = self.SubModel.LearnModel(**self.sub_hn_params)
        try:
            sub_params = sub_model.estimate_params(loss='0-1',dict_out=True)
        except:
            sub_params = sub_model.estimate_params(dict_out=True)
        
        for key,value in sub_params.items():
            try:
                label_string += f'\\l{key}:{value:.2f}'
            except:
                label_string += f'\\l{key}:{value}'
        label_string += '}'

        tree_graph.node(name=f'{tmp_id}',label=label_string,fillcolor=f'{rgb2hex(_CMAP(tmp_p_v))}')
        if tmp_p_v > 0.65:
            tree_graph.node(name=f'{tmp_id}',fontcolor='white')
        
        # add edge information
        if parent_id is not None:
            tree_graph.edge(f'{parent_id}', f'{tmp_id}', label=f'{sibling_num}')
        
        if depth < self.c_d_max and depth < self.c_k:
            for i in range(self.c_num_children):
                node_id = self._visualize_model_recursion_none(tree_graph,depth+1,child_k_candidates,node_id+1,tmp_id,i,tmp_p_v*self.hn_g)
        
        return node_id

    def visualize_posterior(self,filename=None,format=None):
        """Visualize the posterior distribution for the parameter.
        
        This method requires ``graphviz``.

        Parameters
        ----------
        filename : str, optional
            Filename for saving the figure, by default ``None``
        format : str, optional
            Rendering output format (``\"pdf\"``, ``\"png\"``, ...).

        Examples
        --------
        >>> from bayesml import metatree
        >>> gen_model = metatree.GenModel(c_k=3,h_g=0.75)
        >>> gen_model.gen_params()
        >>> x,y = gen_model.gen_sample(500)
        >>> learn_model = metatree.LearnModel(c_k=3)
        >>> learn_model.update_posterior(x,y)
        >>> learn_model.visualize_posterior()

        .. image:: ./images/metatree_posterior.png

        See Also
        --------
        graphviz.Digraph
        """
        try:
            import graphviz
            tree_graph = graphviz.Digraph(filename=filename,format=format)
            tree_graph.attr("node",shape="box",fontname="helvetica",style="rounded,filled")
            if not self.hn_metatree_list:
                self._visualize_model_recursion_none(tree_graph, 0, list(range(self.c_k)), 0, None, None, 1.0)
            else:
                MAP_index = np.argmax(self.hn_metatree_prob_vec)
                print(f'Approximate MAP probability of metatree:{self.hn_metatree_prob_vec[MAP_index]}')
                self._visualize_model_recursion(tree_graph, self.hn_metatree_list[MAP_index], 0, None, None, 1.0)
            # Can we show the image on the console without saving the file?
            tree_graph.view()
        except ImportError as e:
            print(e)
        except graphviz.CalledProcessError as e:
            print(e)
    
    def get_p_params(self):
        """Get the parameters of the predictive distribution.

        This model does not have a simple parametric expression of the predictive distribution.
        Therefore, this function returns ``None``.

        Returns
        -------
        ``None``
        """
        return None
    
    def _calc_pred_dist_leaf(self,node:_Node,x):
            try:
                node.sub_model.calc_pred_dist(x)
            except:
                node.sub_model.calc_pred_dist()

    def _calc_pred_dist_recursion(self,node:_Node,x):
        if node.leaf == False:  # inner node
            self._calc_pred_dist_recursion(node.children[x[node.k]],x)
        else:  # leaf node
            return self._calc_pred_dist_leaf(node,x)

    def calc_pred_dist(self,x):
        """Calculate the parameters of the predictive distribution.
        
        Parameters
        ----------
        x : numpy ndarray
            values of explanatory variables whose dtype is int
        """
        _check.nonneg_int_vec(x,'x',DataFormatError)
        if x.shape[0] != self.c_k:
            raise(DataFormatError(f"x.shape[0] must equal to c_k:{self.c_k}"))
        if x.max() >= self.c_num_children:
            raise(DataFormatError(f"x.max() must smaller than c_num_children:{self.c_num_children}"))
        self._tmp_x[:] = x
        for root in self.hn_metatree_list:
            self._calc_pred_dist_recursion(root,self._tmp_x)

    def _make_prediction_recursion_squared(self,node:_Node):
            if node.leaf == False:  # inner node
                return ((1 - node.h_g) * node.sub_model.make_prediction(loss='squared')
                        + node.h_g * self._make_prediction_recursion_squared(node.children[self._tmp_x[node.k]]))
            else:  # leaf node
                return node.sub_model.make_prediction(loss='squared')

    def _make_prediction_leaf_01(self,node:_Node):
        mode = node.sub_model.make_prediction(loss='0-1')
        pred_dist = node.sub_model.make_prediction(loss='KL')
        if type(pred_dist) is np.ndarray:
            mode_prob = pred_dist[mode]
        else:
            try:
                mode_prob = pred_dist.pdf(mode)
            except:
                try:
                    mode_prob = pred_dist.pmf(mode)
                except:
                    mode_prob = None
        # elif hasattr(pred_dist,'pdf'):
        #     mode_prob = pred_dist.pdf(mode)
        # elif hasattr(pred_dist,'pmf'):
        #     mode_prob = pred_dist.pmf(mode)
        # else:
        #     mode_prob = None
        return mode, mode_prob

    def _make_prediction_recursion_01(self,node:_Node):
        if node.leaf == False:  # inner node
            mode1,mode_prob1 = self._make_prediction_leaf_01(node)
            mode2,mode_prob2 = self._make_prediction_recursion_01(node.children[self._tmp_x[node.k]])
            if (1 - node.h_g) * mode_prob1 > node.h_g * mode_prob2:
                return mode1,mode_prob1
            else:
                return mode2,mode_prob2
        else:  # leaf node
            return self._make_prediction_leaf_01(node)

    def make_prediction(self,loss="0-1"):
        """Predict a new data point under the given criterion.

        Parameters
        ----------
        loss : str, optional
            Loss function underlying the Bayes risk function, by default \"0-1\".
            This function supports \"squared\", \"0-1\".

        Returns
        -------
        predicted_value : {float, numpy.ndarray}
            The predicted value under the given loss function. 
        """
        if loss == "squared":
            tmp_pred_vec = np.empty(len(self.hn_metatree_list))
            for i,metatree in enumerate(self.hn_metatree_list):
                tmp_pred_vec[i] = self._make_prediction_recursion_squared(metatree)
            return self.hn_metatree_prob_vec @ tmp_pred_vec
        elif loss == "0-1":
            tmp_mode = np.empty(len(self.hn_metatree_list))
            tmp_mode_prob_vec = np.empty(len(self.hn_metatree_list))
            for i,metatree in enumerate(self.hn_metatree_list):
                tmp_mode[i],tmp_mode_prob_vec[i] = self._make_prediction_recursion_01(metatree)
            return tmp_mode[np.argmax(self.hn_metatree_prob_vec * tmp_mode_prob_vec)]
        else:
            raise(CriteriaError("Unsupported loss function! "
                                +"This function supports \"squared\" and \"0-1\"."))

    def pred_and_update(self,x,y,loss="0-1"):
        """Predict a new data point and update the posterior sequentially.

        Parameters
        ----------
        x : numpy.ndarray
            It must be a degree-dimensional vector
        y : numpy ndarray
            values of objective variable whose dtype may be int or float
        loss : str, optional
            Loss function underlying the Bayes risk function, by default \"0-1\".
            This function supports \"squared\", \"0-1\", and \"KL\".

        Returns
        -------
        predicted_value : {float, numpy.ndarray}
            The predicted value under the given loss function. 
        """
        _check.nonneg_int_vec(x,'x',DataFormatError)
        if x.shape[-1] != self.c_k:
            raise(DataFormatError(f"x.shape[-1] must equal to c_k:{self.c_k}"))
        if x.max() >= self.c_num_children:
            raise(DataFormatError(f"x.max() must smaller than c_num_children:{self.c_num_children}"))
        self.calc_pred_dist(x)
        prediction = self.make_prediction(loss=loss)
        self.update_posterior(x,y,alg_type='given_MT')
        return prediction
