import numpy as np
import pandas as pd
import torch
from typing import Optional, Dict
from sklearn.preprocessing import LabelEncoder
from torch_choice.data import ChoiceDataset


class EasyDatasetWrapper():
    """An easy-to-use interface for creating ChoiceDataset object, please refer to the doc-string of the `__init__` method
    for more details.

    Raises:
        ValueError: _description_
        ValueError: _description_

    Returns:
        _type_: _description_
    """
    SUPPORTED_FORMATS = ['stata']

    def __init__(self,
                 main_data: pd.DataFrame,
                 purchase_record_column: str,
                 item_name_column: str,
                 choice_column: str,
                 user_index_column: Optional[str] = None,
                 session_index_column: Optional[str] = None,
                 user_observable_data: Optional[Dict[str, pd.DataFrame]] = dict(),
                 item_observable_data: Optional[Dict[str, pd.DataFrame]] = dict(),
                 session_observable_data: Optional[Dict[str, pd.DataFrame]] = dict(),
                 price_observable_data: Optional[Dict[str, pd.DataFrame]] = dict(),
                 format: str = 'stata'):
        """The initialization method of EasyDatasetWrapper.

        Args:
            main_data (pd.DataFrame): the main dataset holding all purchase records in a "long-format", each row of the
                dataset is an item in a purchase record. #TODO: elaborate this.
                The main_data data-frame should contains the following columns:
            purchase_record_column (str): the column in main_data identifies the index of purchasing records.
            item_name_column (str): the column in main_data identifies the name of items.
            choice_column (str): the column in the main_data identifies the bought item, for all rows with the same value
                of `purchase_record_column`, there should be exactly one row with `choice_column` equal to 1, all
                other rows should be 0.
            user_index_column (Optional[str], optional): an optional column indicating the user in each purchasing records,
                values should be constant across all rows with the same `purchase_record_column`. Defaults to None.
            session_index_column (Optional[str], optional): an optional column indicating the session in each purchasing records,
                values should be constant across all rows with the same `purchase_record_column`. Defaults to None.

            The keys of all of *_observable_data are the name of the observable data.

            user_observable_data (Optional[Dict[str, pd.DataFrame]], optional): a dictionary with keys as the name of each
                observable. The values should be a pandas data-frame indexed by values in main_data[user_index_column], the
                name of the index column should be the same as user_index_column. Defaults to dict().
            item_observable_data (Optional[Dict[str, pd.DataFrame]], optional): a dictionary with keys as the name of each
                observable. The values should be a pandas data-frame indexed by values in main_data[item_name_column], the
                name of the index column should be the same as item_name_column. Defaults to dict().
            session_observable_data (Optional[Dict[str, pd.DataFrame]], optional): a dictionary with keys as the name of each
                observable. The values should be a pandas data-frame indexed by values in main_data[session_index_column],
                name of the index column should be the same as session_index_column. Defaults to dict().
            price_observable_data (Optional[Dict[str, pd.DataFrame]], optional): a dictionary with keys as the name of each
                observable. The values should be a pandas data-frame multi-indexed by values in main_data[session_index_column]
                and main_data[item_name_column], the first level name should be the same as session_index_column, the second
                level name should be the same as item_name_column. Defaults to dict().

            format (str, optional): the input format of the dataset. Defaults to 'stata'.

        Raises:
            ValueError: _description_
        """

        if format not in self.SUPPORTED_FORMATS:
            raise ValueError(f'Format {format} is not supported, only {self.SUPPORTED_FORMATS} are supported.')

        self.main_data = main_data

        self.purchase_record_column = purchase_record_column
        self.purchase_record_index = main_data[purchase_record_column].unique()
        self.item_name_column = item_name_column
        self.choice_column = choice_column
        self.user_index_column = user_index_column
        self.session_index_column = session_index_column

        self.encode()

        self.align_observable_data(item_observable_data, user_observable_data, session_observable_data, price_observable_data)

        self.observable_data_to_observable_tensors()

        self.create_choice_dataset_from_stata()

    def encode(self) -> None:
        """Encodes item names, user names, and session names to {0, 1, 2, ...} integers."""
        self.item_name_encoder = LabelEncoder().fit(self.main_data[self.item_name_column].unique())

        if self.user_index_column is not None:
            self.user_name_encoder = LabelEncoder().fit(self.main_data[self.user_index_column].unique())

        if self.session_index_column is not None:
            self.session_name_encoder = LabelEncoder().fit(self.main_data[self.session_index_column].unique())

    def align_observable_data(self, item_observable_data, user_observable_data, session_observable_data, price_observable_data) -> None:
        self.item_observable_data = dict()
        for key, val in item_observable_data.items():
            self.item_observable_data['item_' + key] = val.loc[self.item_name_encoder.classes_]

        self.user_observable_data = dict()
        for key, val in user_observable_data.items():
            assert self.user_index_column is not None, 'user observable data is provided but user index column is not provided.'
            self.user_observable_data['user_' + key] = val.loc[self.user_name_encoder.classes_]

        self.session_observable_data = dict()
        for key, val in session_observable_data.items():
            assert self.session_index_column is not None, 'session observable data is provided but session index column is not provided.'
            self.session_observable_data['session_' + key] = val.loc[self.session_name_encoder.classes_]

        self.price_observable_data = dict()
        for key, val in price_observable_data.items():
            assert self.session_index_column is not None, 'price observable data is provided but session index column is not provided.'
            # need to re-index since some alternatives might be unavailable in some session, re-indexing ensure that
            # we have len(price_obs) == num_sessions * num_items and allows for easier pivoting later.
            complete_index = pd.MultiIndex.from_product([self.session_name_encoder.classes_, self.item_name_encoder.classes_],
                                                        names=[self.session_index_column, self.item_name_column])
            self.price_observable_data['price_' + key] = val.reindex(complete_index)

    def observable_data_to_observable_tensors(self):
        """Convert all self.*_observable_data to self.*_observable_tensors for PyTorch."""
        self.item_observable_tensors = dict()
        for key, val in self.item_observable_data.items():
            self.item_observable_tensors[key] = torch.tensor(val.loc[self.item_name_encoder.classes_].values, dtype=torch.float32)

        self.user_observable_tensors = dict()
        for key, val in self.user_observable_data.items():
            self.user_observable_tensors[key] = torch.tensor(val.loc[self.user_name_encoder.classes_].values, dtype=torch.float32)

        self.session_observable_tensors = dict()
        for key, val in self.session_observable_data.items():
            self.session_observable_tensors[key] = torch.tensor(val.loc[self.session_name_encoder.classes_].values, dtype=torch.float32)

        self.price_observable_tensors = dict()
        for key, val in self.price_observable_data.items():
            tensor_slice = list()
            for column in val.columns:
                df_slice = val.reset_index().pivot(index=self.session_index_column, columns=self.item_name_column, values=column)
                tensor_slice.append(torch.tensor(df_slice.values, dtype=torch.float32))

                assert np.all(df_slice.index == self.session_name_encoder.classes_)
                assert np.all(df_slice.columns == self.item_name_encoder.classes_)

            self.price_observable_tensors[key] = torch.stack(tensor_slice, dim=-1)

    def create_choice_dataset_from_stata(self):
        print('Creating choice dataset from stata format data-frames...')
        choice_set_size = self.main_data.groupby(self.purchase_record_column)[self.item_name_column].nunique()
        s = choice_set_size.value_counts()
        rep = dict(zip([f'size {x}' for x in s.index], [f'occurrence {x}' for x in s.values]))
        if len(np.unique(choice_set_size)) > 1:
            print(f'Note: choice sets of different sizes found in different purchase records: {rep}')
            self.item_availability = self.get_item_availability_tensor()

        item_bought = self.main_data[self.main_data[self.choice_column] == 1].set_index(self.purchase_record_column).loc[self.purchase_record_index, self.item_name_column].values
        self.item_index = self.item_name_encoder.transform(item_bought)

        # user index
        if self.user_index_column is None:
            self.user_index = None
        else:
            # get the user index of each purchase record.
            self.user_index = self.main_data.groupby(self.purchase_record_column)[self.user_index_column].first().loc[self.purchase_record_index].values
            self.user_index = self.user_name_encoder.transform(self.user_index)

        # session index
        if self.session_index_column is None:
            # print('Note: no session index provided, assign each case/purchase record to a unique session index.')
            self.session_index = None
        else:
            self.session_index = self.main_data.groupby(self.purchase_record_column)[self.session_index_column].first().loc[self.purchase_record_index].values
            self.session_index = self.session_name_encoder.transform(self.session_index)

        self.choice_dataset = ChoiceDataset(item_index=torch.LongTensor(self.item_index),
                                            user_index=torch.LongTensor(self.user_index) if self.user_index is not None else None,
                                            session_index=torch.LongTensor(self.session_index) if self.session_index is not None else None,
                                            item_availability=self.item_availability,
                                            **self.item_observable_tensors,
                                            **self.user_observable_tensors,
                                            **self.session_observable_tensors,
                                            **self.price_observable_tensors)

    def get_item_availability_tensor(self) -> torch.BoolTensor:
        if self.session_index_column is None:
            raise ValueError(f'Item availability cannot be constructed without session index column.')
        A = self.main_data.pivot(self.session_index_column, self.item_name_column, self.choice_column)
        return torch.BoolTensor(~np.isnan(A.values))

    def __len__(self):
        return len(self.item_index)

    def summary(self):
        print(f'* Space of {len(self.item_name_encoder.classes_)} items:\n', pd.DataFrame(data={'item name': self.item_name_encoder.classes_}, index=np.arange(len(self.item_name_encoder.classes_))).T)
        print(f'* Number of purchase records/cases: {len(self)}.')
        print('* Preview of main data frame:')
        print(self.main_data)
        print('* Preview of ChoiceDataset:')
        print(self.choice_dataset)
