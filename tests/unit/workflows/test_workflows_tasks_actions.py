# -*- coding: utf-8 -*-
#
# This file is part of INSPIRE.
# Copyright (C) 2014-2017 CERN.
#
# INSPIRE is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# INSPIRE is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with INSPIRE. If not, see <http://www.gnu.org/licenses/>.
#
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization
# or submit itself to any jurisdiction.

from __future__ import absolute_import, division, print_function

import os
import pkg_resources

import pytest
import requests_mock
from flask import current_app
from mock import patch

from inspire_schemas.api import load_schema, validate
from inspirehep.modules.workflows.tasks.actions import (
    _is_auto_rejected,
    add_core,
    fix_submission_number,
    halt_record,
    in_production_mode,
    is_arxiv_paper,
    is_experimental_paper,
    is_marked,
    is_record_accepted,
    is_record_relevant,
    is_submission,
    mark,
    populate_journal_coverage,
    refextract,
    reject_record,
    set_refereed_and_fix_document_type,
    shall_halt_workflow,
    submission_fulltext_download,
)
from inspirehep.utils.url import retrieve_uri

from mocks import MockEng, MockObj, MockFiles


def _get_auto_reject_obj(decision, has_core_keywords):
    obj_params = {
        'classifier_results': {
            'complete_output': {
                'core_keywords': ['something'] if has_core_keywords else [],
            },
        },
        'relevance_prediction': {
            'max_score': '0.222113',
            'decision': decision,
        },
    }

    return MockObj({}, obj_params)


def test_mark():
    obj = MockObj({}, {})
    eng = MockEng()

    foobar_mark = mark('foo', 'bar')

    assert foobar_mark(obj, eng) is None
    assert obj.extra_data == {'foo': 'bar'}


def test_mark_overwrites():
    obj = MockObj({}, {'foo': 'bar'})
    eng = MockEng()

    foobaz_mark = mark('foo', 'baz')

    assert foobaz_mark(obj, eng) is None
    assert obj.extra_data == {'foo': 'baz'}


def test_is_marked():
    obj = MockObj({}, {'foo': 'bar'})
    eng = MockEng()

    is_foo_marked = is_marked('foo')

    assert is_foo_marked(obj, eng)


def test_is_marked_returns_false_when_key_does_not_exist():
    obj = MockObj({}, {})
    eng = MockEng()

    is_foo_marked = is_marked('foo')

    assert not is_foo_marked(obj, eng)


def test_is_marked_returns_false_when_value_is_falsy():
    obj = MockObj({}, {'foo': False})
    eng = MockEng()

    is_foo_marked = is_marked('foo')

    assert not is_foo_marked(obj, eng)


def test_is_record_accepted():
    obj = MockObj({}, {'approved': True})

    assert is_record_accepted(obj)


def test_is_record_accepted_returns_false_when_key_does_not_exist():
    obj = MockObj({}, {})

    assert not is_record_accepted(obj)


def test_is_record_accepted_returns_false_when_value_is_falsy():
    obj = MockObj({}, {'approved': False})

    assert not is_record_accepted(obj)


def test_shall_halt_workflow():
    obj = MockObj({}, {'halt_workflow': True})

    assert shall_halt_workflow(obj)


def test_shall_halt_workflow_returns_false_when_key_does_not_exist():
    obj = MockObj({}, {})

    assert not shall_halt_workflow(obj)


def test_shall_halt_workflow_returns_false_when_value_is_falsy():
    obj = MockObj({}, {'halt_workflow': False})

    assert not shall_halt_workflow(obj)


def test_in_production_mode():
    config = {'PRODUCTION_MODE': True}

    with patch.dict(current_app.config, config):
        assert in_production_mode()


def test_in_production_mode_returns_false_when_variable_does_not_exist():
    config = {}

    with patch.dict(current_app.config, config, clear=True):
        assert not in_production_mode()


def test_in_production_mode_returns_false_when_variable_is_falsy():
    config = {'PRODUCTION_MODE': False}

    with patch.dict(current_app.config, config):
        assert not in_production_mode()


def test_add_core_sets_core_to_true_if_extra_data_core_is_true():
    obj = MockObj({}, {'core': True})
    eng = MockEng()

    assert add_core(obj, eng) is None
    assert obj.data == {'core': True}


def test_add_core_sets_core_to_false_if_extra_data_core_is_false():
    obj = MockObj({}, {'core': False})
    eng = MockEng()

    assert add_core(obj, eng) is None
    assert obj.data == {'core': False}


def test_add_core_does_nothing_if_extra_data_has_no_core_key():
    obj = MockObj({}, {})
    eng = MockEng()

    assert add_core(obj, eng) is None
    assert obj.data == {}


def test_add_core_overrides_core_if_extra_data_has_core_key():
    obj = MockObj({'core': False}, {'core': True})
    eng = MockEng()

    assert add_core(obj, eng) is None
    assert obj.data == {'core': True}


def test_halt_record():
    obj = MockObj({}, {'halt_action': 'foo', 'halt_message': 'bar'})
    eng = MockEng()

    default_halt_record = halt_record()

    assert default_halt_record(obj, eng) is None
    assert eng.action == 'foo'
    assert eng.msg == 'bar'


def test_halt_record_accepts_custom_action():
    obj = MockObj({}, {})
    eng = MockEng()

    foo_action_halt_record = halt_record(action='foo')

    assert foo_action_halt_record(obj, eng) is None
    assert eng.action == 'foo'


def test_halt_record_accepts_custom_msg():
    obj = MockObj({}, {})
    eng = MockEng()

    bar_message_halt_record = halt_record(message='bar')

    assert bar_message_halt_record(obj, eng) is None
    assert eng.msg == 'bar'


@patch('inspirehep.modules.workflows.tasks.actions.log_workflows_action')
def test_reject_record(l_w_a):
    obj = MockObj({}, {
        'relevance_prediction': {
            'max_score': '0.222113',
            'decision': 'Rejected',
        },
    })

    foo_reject_record = reject_record('foo')

    assert foo_reject_record(obj) is None
    assert obj.extra_data == {
        'approved': False,
        'reason': 'foo',
        'relevance_prediction': {
            'decision': 'Rejected',
            'max_score': '0.222113',
        },
    }
    assert obj.log._info.getvalue() == 'foo'
    l_w_a.assert_called_once_with(
        action='reject_record',
        relevance_prediction={
            'decision': 'Rejected',
            'max_score': '0.222113',
        },
        object_id=1,
        user_id=None,
        source='workflow',
    )


@pytest.mark.parametrize(
    'expected,obj',
    [
        (False, _get_auto_reject_obj('Core', has_core_keywords=False)),
        (False, _get_auto_reject_obj('Non-Core', has_core_keywords=False)),
        (True, _get_auto_reject_obj('Rejected', has_core_keywords=False)),
        (False, _get_auto_reject_obj('Core', has_core_keywords=True)),
        (False, _get_auto_reject_obj('Non-Core', has_core_keywords=True)),
        (False, _get_auto_reject_obj('Rejected', has_core_keywords=True)),
    ],
    ids=[
        'Dont reject: No core keywords with core decision',
        'Dont reject: No core keywords with non-core decision',
        'Reject: No core keywords with rejected decision',
        'Dont reject: Core keywords with core decision',
        'Dont reject: Core keywords with non-core decision',
        'Dont reject: Core keywords with rejected decision',
    ]
)
def test__is_auto_rejected(expected, obj):
    assert _is_auto_rejected(obj) is expected


@pytest.mark.parametrize(
    'expected,should_submission,should_auto_reject',
    [
        (True, True, True),
        (True, True, False),
        (False, False, True),
        (True, False, False),
    ],
    ids=[
        'Relevant: is submission and autorejected',
        'Relevant: is submission and not autorejected',
        'Not relevant: is not submission and autorejected',
        'Relevant: is not submission and not autorejected',
    ]
)
@patch('inspirehep.modules.workflows.tasks.actions.is_submission')
@patch('inspirehep.modules.workflows.tasks.actions._is_auto_rejected')
def test_is_record_relevant(
    _is_auto_rejected_mock,
    is_submission_mock,
    expected,
    should_submission,
    should_auto_reject,
):
    _is_auto_rejected_mock.return_value = should_auto_reject
    is_submission_mock.return_value = should_submission
    obj = object()
    eng = object()

    assert is_record_relevant(obj, eng) is expected


def test_is_experimental_paper():
    obj = MockObj({
        'arxiv_eprints': [
            {'categories': ['hep-ex']},
        ]
    }, {})
    eng = MockEng()

    assert is_experimental_paper(obj, eng)


def test_is_experimental_paper_returns_true_if_inspire_categories_in_list():
    obj = MockObj({'inspire_categories': [{'term': 'Experiment-HEP'}]}, {})
    eng = MockEng()

    assert is_experimental_paper(obj, eng)


def test_is_experimental_paper_returns_false_otherwise():
    obj = MockObj({}, {})
    eng = MockEng()

    assert not is_experimental_paper(obj, eng)


def test_is_arxiv_paper():
    obj = MockObj({
        'arxiv_eprints': [
            {
                'categories': ['hep-th'],
                'value': 'oai:arXiv.org:0801.4782',
            },
        ],
    }, {})

    assert is_arxiv_paper(obj)


def test_is_arxiv_paper_returns_false_when_arxiv_eprints_is_empty():
    obj = MockObj({'arxiv_eprints': []}, {})

    assert not is_arxiv_paper(obj)


def test_is_submission():
    obj = MockObj({'acquisition_source': {'method': 'submitter'}}, {})
    eng = MockEng()

    assert is_submission(obj, eng)


def test_is_submission_returns_false_if_method_is_not_submission():
    obj = MockObj({'acquisition_source': {'method': 'not-submission'}}, {})
    eng = MockEng()

    assert not is_submission(obj, eng)


def test_is_submission_returns_false_if_obj_has_no_acquisition_source():
    obj = MockObj({}, {})
    eng = MockEng()

    assert not is_submission(obj, eng)


def test_is_submission_returns_false_if_obj_has_falsy_acquisition_source():
    obj = MockObj({}, {})
    eng = MockEng()

    assert not is_submission(obj, eng)


def test_fix_submission_number():
    schema = load_schema('hep')
    subschema = schema['properties']['acquisition_source']

    data = {
        'acquisition_source': {
            'method': 'hepcrawl',
            'submission_number': '751e374a017311e896d6fa163ec92c6a',
        },
    }
    extra_data = {}
    assert validate(data['acquisition_source'], subschema) is None

    obj = MockObj(data, extra_data)
    eng = MockEng()

    fix_submission_number(obj, eng)

    expected = {
        'method': 'hepcrawl',
        'submission_number': '1',
    }
    result = obj.data['acquisition_source']

    assert validate(result, subschema) is None
    assert expected == result


def fix_submission_number_does_nothing_if_method_is_not_hepcrawl():
    schema = load_schema('hep')
    subschema = schema['properties']['acquisition_source']

    data = {
        'acquisition_source': {
            'method': 'submitter',
            'submission_number': '869215',
        },
    }
    extra_data = {}
    assert validate(data['acquisition_source'], subschema) is None

    obj = MockObj(data, extra_data)
    eng = MockEng()

    fix_submission_number(obj, eng)

    expected = {
        'method': 'submitter',
        'submission_number': '869215',
    }
    result = obj.data['acquisition_source']

    assert validate(result, subschema) is None
    assert expected == result


@patch('inspirehep.modules.workflows.tasks.actions.replace_refs')
def test_populate_journal_coverage_writes_full_if_any_coverage_is_full(mock_replace_refs):
    schema = load_schema('journals')
    subschema = schema['properties']['_harvesting_info']

    journals = [{'_harvesting_info': {'coverage': 'full'}}]
    assert validate(journals[0]['_harvesting_info'], subschema) is None

    mock_replace_refs.return_value = journals

    schema = load_schema('hep')
    subschema = schema['properties']['publication_info']

    data = {
        'publication_info': [
            {'journal_record': {'$ref': 'http://localhost:/api/journals/1213103'}},
        ],
    }
    extra_data = {}
    assert validate(data['publication_info'], subschema) is None

    obj = MockObj(data, extra_data)
    eng = MockEng()

    assert populate_journal_coverage(obj, eng) is None

    expected = 'full'
    result = obj.extra_data['journal_coverage']

    assert expected == result


@patch('inspirehep.modules.workflows.tasks.actions.replace_refs')
def test_populate_journal_coverage_writes_partial_if_all_coverages_are_partial(mock_replace_refs):
    schema = load_schema('journals')
    subschema = schema['properties']['_harvesting_info']

    journals = [{'_harvesting_info': {'coverage': 'partial'}}]
    assert validate(journals[0]['_harvesting_info'], subschema) is None

    mock_replace_refs.return_value = journals

    schema = load_schema('hep')
    subschema = schema['properties']['publication_info']

    data = {
        'publication_info': [
            {'journal_record': {'$ref': 'http://localhost:/api/journals/1212337'}},
        ],
    }
    extra_data = {}
    assert validate(data['publication_info'], subschema) is None

    obj = MockObj(data, extra_data)
    eng = MockEng()

    assert populate_journal_coverage(obj, eng) is None

    expected = 'partial'
    result = obj.extra_data['journal_coverage']

    assert expected == result


@patch('inspirehep.modules.workflows.tasks.actions.replace_refs')
def test_populate_journal_coverage_does_nothing_if_no_journal_is_found(mock_replace_refs):
    mock_replace_refs.return_value = []

    data = {}
    extra_data = {}

    obj = MockObj(data, extra_data)
    eng = MockEng()

    assert populate_journal_coverage(obj, eng) is None
    assert 'journal_coverage' not in obj.extra_data


@patch('inspirehep.modules.workflows.tasks.actions.get_pdf_in_workflow')
def test_refextract_from_pdf(mock_get_pdf_in_workflow):
    mock_get_pdf_in_workflow.return_value = retrieve_uri(
        pkg_resources.resource_filename(
            __name__,
            os.path.join('fixtures', '1704.00452.pdf'),
        )
    )

    schema = load_schema('hep')
    subschema = schema['properties']['acquisition_source']

    data = {'acquisition_source': {'source': 'arXiv'}}
    extra_data = {}
    assert validate(data['acquisition_source'], subschema) is None

    obj = MockObj(data, extra_data)
    eng = MockEng()

    assert refextract(obj, eng) is None
    assert obj.data['references'][0]['raw_refs'][0]['source'] == 'arXiv'


@patch('inspirehep.modules.workflows.tasks.actions.get_pdf_in_workflow')
def test_refextract_from_text(mock_get_pdf_in_workflow):
    mock_get_pdf_in_workflow.return_value = None

    schema = load_schema('hep')
    subschema = schema['properties']['acquisition_source']

    data = {'acquisition_source': {'source': 'submitter'}}
    extra_data = {
        'formdata': {
            'references': 'M.R. Douglas, G.W. Moore, D-branes, quivers, and ALE instantons, arXiv:hep-th/9603167',
        },
    }
    assert validate(data['acquisition_source'], subschema) is None

    obj = MockObj(data, extra_data)
    eng = MockEng()

    assert refextract(obj, eng) is None
    assert obj.data['references'][0]['raw_refs'][0]['source'] == 'submitter'


def test_submission_fulltext_download():
    with requests_mock.Mocker() as requests_mocker:
        requests_mocker.register_uri(
            'GET', 'http://export.arxiv.org/pdf/1605.03844',
            content=pkg_resources.resource_string(
                __name__, os.path.join('fixtures', '1605.03844.pdf')),
        )

        schema = load_schema('hep')
        subschema = schema['properties']['acquisition_source']
        data = {
            'acquisition_source': {
                'datetime': '2017-11-30T16:38:43.352370',
                'email': 'david.caro@cern.ch',
                'internal_uid': 54252,
                'method': 'submitter',
                'orcid': '0000-0002-2174-4493',
                'source': 'submitter',
                'submission_number': '1'
            }
        }
        assert validate(data['acquisition_source'], subschema) is None

        extra_data = {
            'submission_pdf': 'http://export.arxiv.org/pdf/1605.03844',
        }
        files = MockFiles({})
        obj = MockObj(data, extra_data, files=files)
        eng = MockEng()

        assert submission_fulltext_download(obj, eng)

        expected_key = 'fulltext.pdf'
        expected_documents = [
            {
                'fulltext': True,
                'key': expected_key,
                'original_url': 'http://export.arxiv.org/pdf/1605.03844',
                'source': 'submitter',
                'url': '/api/files/%s/%s' % (
                    obj.files[expected_key].bucket_id,
                    expected_key,
                ),
            }
        ]
        result = obj.data['documents']

        assert expected_documents == result


def test_submission_fulltext_download_does_not_duplicate_documents():
    with requests_mock.Mocker() as requests_mocker:
        requests_mocker.register_uri(
            'GET', 'http://export.arxiv.org/pdf/1605.03844',
            content=pkg_resources.resource_string(
                __name__, os.path.join('fixtures', '1605.03844.pdf')),
        )

        schema = load_schema('hep')
        subschema = schema['properties']['acquisition_source']
        data = {
            'acquisition_source': {
                'datetime': '2017-11-30T16:38:43.352370',
                'email': 'david.caro@cern.ch',
                'internal_uid': 54252,
                'method': 'submitter',
                'orcid': '0000-0002-2174-4493',
                'source': 'submitter',
                'submission_number': '1'
            }
        }
        assert validate(data['acquisition_source'], subschema) is None

        extra_data = {
            'submission_pdf': 'http://export.arxiv.org/pdf/1605.03844',
        }
        files = MockFiles({})
        obj = MockObj(data, extra_data, files=files)
        eng = MockEng()

        assert submission_fulltext_download(obj, eng)
        assert submission_fulltext_download(obj, eng)

        expected_key = 'fulltext.pdf'
        expected_documents = [
            {
                'fulltext': True,
                'key': expected_key,
                'original_url': 'http://export.arxiv.org/pdf/1605.03844',
                'source': 'submitter',
                'url': '/api/files/%s/%s' % (
                    obj.files[expected_key].bucket_id,
                    expected_key,
                ),
            }
        ]
        result = obj.data['documents']

        assert expected_documents == result


@patch('inspirehep.modules.workflows.tasks.actions.replace_refs')
def test_set_refereed_and_fix_document_type(mock_replace_refs):
    schema = load_schema('journals')
    subschema = schema['properties']['refereed']

    journals = [{'refereed': True}]
    assert validate(journals[0]['refereed'], subschema) is None

    mock_replace_refs.return_value = journals

    schema = load_schema('hep')
    subschema = schema['properties']['refereed']

    data = {'document_type': ['article']}
    extra_data = {}

    obj = MockObj(data, extra_data)
    eng = MockEng()

    assert set_refereed_and_fix_document_type(obj, eng) is None

    expected = True
    result = obj.data['refereed']

    assert validate(result, subschema) is None
    assert expected == result


@patch('inspirehep.modules.workflows.tasks.actions.replace_refs')
def test_set_refereed_and_fix_document_type_handles_journals_that_publish_mixed_content(mock_replace_refs):
    schema = load_schema('journals')
    proceedings_schema = schema['properties']['proceedings']
    refereed_schema = schema['properties']['refereed']

    journals = [{'proceedings': True, 'refereed': True}]
    assert validate(journals[0]['proceedings'], proceedings_schema) is None
    assert validate(journals[0]['refereed'], refereed_schema) is None

    mock_replace_refs.return_value = journals

    schema = load_schema('hep')
    subschema = schema['properties']['refereed']

    data = {'document_type': ['article']}
    extra_data = {}

    obj = MockObj(data, extra_data)
    eng = MockEng()

    assert set_refereed_and_fix_document_type(obj, eng) is None

    expected = True
    result = obj.data['refereed']

    assert validate(result, subschema) is None
    assert expected == result


@patch('inspirehep.modules.workflows.tasks.actions.replace_refs')
def test_set_refereed_and_fix_document_type_sets_refereed_to_false_if_all_journals_are_not_refereed(mock_replace_refs):
    schema = load_schema('journals')
    subschema = schema['properties']['refereed']

    journals = [{'refereed': False}]
    assert validate(journals[0]['refereed'], subschema) is None

    mock_replace_refs.return_value = journals

    schema = load_schema('hep')
    subschema = schema['properties']['refereed']

    data = {'document_type': ['article']}
    extra_data = {}

    obj = MockObj(data, extra_data)
    eng = MockEng()

    assert set_refereed_and_fix_document_type(obj, eng) is None

    expected = False
    result = obj.data['refereed']

    assert validate(result, subschema) is None
    assert expected == result


@patch('inspirehep.modules.workflows.tasks.actions.replace_refs')
def test_set_refereed_and_fix_document_type_replaces_article_with_conference_paper_if_needed(mock_replace_refs):
    schema = load_schema('journals')
    subschema = schema['properties']['proceedings']

    journals = [{'proceedings': True}]
    assert validate(journals[0]['proceedings'], subschema) is None

    mock_replace_refs.return_value = journals

    schema = load_schema('hep')
    subschema = schema['properties']['document_type']

    data = {'document_type': ['article']}
    extra_data = {}

    obj = MockObj(data, extra_data)
    eng = MockEng()

    assert set_refereed_and_fix_document_type(obj, eng) is None

    expected = ['conference paper']
    result = obj.data['document_type']

    assert validate(result, subschema) is None
    assert expected == result


@patch('inspirehep.modules.workflows.tasks.actions.replace_refs')
def test_set_refereed_and_fix_document_type_does_nothing_if_no_journals_were_found(mock_replace_refs):
    mock_replace_refs.return_value = []

    data = {'document_type': ['article']}
    extra_data = {}

    obj = MockObj(data, extra_data)
    eng = MockEng()

    assert set_refereed_and_fix_document_type(obj, eng) is None
    assert 'refereed' not in obj.data
