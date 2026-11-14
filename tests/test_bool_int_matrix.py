"""
Four-state matrix regression tests for the boolean/integer classification.

A warehouse reconciliation payload mixes flag bits (Python ``bool``) and
counters (``int``). Because ``bool`` subclasses ``int`` and ``True == 1`` (with
equal hashes), the four container kinds used to disagree:

* ordered list                -> silently reported nothing
* dict                        -> reported a type change
* list with ignore_order=True -> reported a type change
* set / frozenset             -> reported a phantom add plus a phantom remove

These tests pin the unified contract: every container classifies an
equal-valued bool/int pair as ``type_changes`` with the same value shape, while
genuine type changes, plain value changes, string changes and the
``ignore_numeric_type_changes`` escape hatch keep their existing behavior.
"""
import pytest

from deepdiff import DeepDiff
from deepdiff.diff import DeepDiff as _DeepDiff


def _type_change_entry(old_value, new_value, old_type, new_type):
    return {
        'old_type': old_type,
        'new_type': new_type,
        'old_value': old_value,
        'new_value': new_value,
    }


class TestBoolIntFourStateMatrix:
    """The four container kinds must classify bool/int identically."""

    @pytest.mark.parametrize(
        'container, expected_path',
        [
            ('ordered_list', 'root[0]'),
            ('ignore_order_list', 'root[0]'),
            ('dict', "root['a']"),
            ('set', None),  # path depends on direction, asserted per case below
        ],
    )
    @pytest.mark.parametrize(
        'old_value, new_value, old_type, new_type',
        [
            (1, True, int, bool),
            (True, 1, bool, int),
            (0, False, int, bool),
            (False, 0, bool, int),
        ],
    )
    def test_every_container_reports_type_change(
            self, container, expected_path, old_value, new_value, old_type, new_type):
        if container == 'ordered_list':
            result = DeepDiff([old_value], [new_value])
            path = expected_path
        elif container == 'ignore_order_list':
            result = DeepDiff([old_value], [new_value], ignore_order=True)
            path = expected_path
        elif container == 'dict':
            result = DeepDiff({'a': old_value}, {'a': new_value})
            path = expected_path
        else:
            result = DeepDiff({old_value}, {new_value})
            # Set elements are addressed by value (root[value]); the t1 value is
            # the anchor, matching the existing set_item_* path convention.
            path = 'root[{}]'.format(old_value)

        assert result == {
            'type_changes': {
                path: _type_change_entry(old_value, new_value, old_type, new_type)
            }
        }

    def test_frozenset_uses_same_classification_as_set(self):
        result = DeepDiff(frozenset({1}), frozenset({True}))
        assert result == {
            'type_changes': {
                'root[1]': _type_change_entry(1, True, int, bool)
            }
        }

    def test_four_containers_identical_value_shape_int_to_bool(self):
        """Same logical change, four containers -> same category + value shape."""
        results = [
            DeepDiff([1], [True]),
            DeepDiff([1], [True], ignore_order=True),
            DeepDiff({'k': 1}, {'k': True}),
            DeepDiff({1}, {True}),
        ]
        for result in results:
            assert set(result.keys()) == {'type_changes'}
            entry = list(result['type_changes'].values())[0]
            assert entry == _type_change_entry(1, True, int, bool)

    def test_four_containers_identical_value_shape_bool_to_int(self):
        results = [
            DeepDiff([True], [1]),
            DeepDiff([True], [1], ignore_order=True),
            DeepDiff({'k': True}, {'k': 1}),
            DeepDiff({True}, {1}),
        ]
        for result in results:
            assert set(result.keys()) == {'type_changes'}
            entry = list(result['type_changes'].values())[0]
            assert entry == _type_change_entry(True, 1, bool, int)

    def test_set_no_phantom_add_or_remove(self):
        result = DeepDiff({1}, {True})
        assert 'set_item_added' not in result
        assert 'set_item_removed' not in result
        assert 'type_changes' in result

    def test_set_mixed_real_change_and_type_change(self):
        # One genuine removal/addition pair plus one bool/int type change.
        result = DeepDiff({1, 9}, {True, 10})
        assert result['set_item_removed'] == {'root[9]'}
        assert result['set_item_added'] == {'root[10]'}
        type_entry = list(result['type_changes'].values())[0]
        assert type_entry == _type_change_entry(1, True, int, bool)

    def test_set_multiple_bool_int_pairs_are_one_to_one(self):
        # Both 1/True and 0/False collide by value but differ by type.
        result = DeepDiff({1, 2, False}, {True, 2, 0})
        assert 'set_item_added' not in result
        assert 'set_item_removed' not in result
        assert set(result['type_changes'].keys()) == {'root[1]', 'root[False]'}


class TestBoolIntIgnoreNumericTypeChanges:
    """When numeric type changes are ignored, all four containers stay silent."""

    @pytest.mark.parametrize(
        't1, t2, extra',
        [
            ([1], [True], {}),
            ([True], [1], {}),
            ({'a': 1}, {'a': True}, {}),
            ({'a': True}, {'a': 1}, {}),
            ([1], [True], {'ignore_order': True}),
            ([True], [1], {'ignore_order': True}),
            ({1}, {True}, {}),
            ({True}, {1}, {}),
            (frozenset({1}), frozenset({True}), {}),
        ],
    )
    def test_silent_when_numeric_types_ignored(self, t1, t2, extra):
        assert DeepDiff(t1, t2, ignore_numeric_type_changes=True, **extra) == {}


class TestBoolIntNonRegressions:
    """Behavior outside the bool/int boundary must not move."""

    def test_pure_bool_value_change_still_values_changed(self):
        # bool vs bool is a value change, never a type change.
        t1 = [False, False, True, True]
        t2 = [False, False, False, True]
        assert DeepDiff(t1, t2) == {
            'values_changed': {'root[2]': {'new_value': False, 'old_value': True}}}

    def test_set_real_type_change_still_add_remove(self):
        result = DeepDiff({1}, {'1'})
        assert result == {'set_item_removed': {'root[1]'}, 'set_item_added': {"root['1']"}}

    def test_set_unequal_bool_int_still_add_remove(self):
        # True != 2, so there is no equal-valued pair to reconcile.
        result = DeepDiff({True}, {2})
        assert result == {'set_item_removed': {'root[True]'}, 'set_item_added': {'root[2]'}}

    def test_float_is_outside_bool_int_scope(self):
        # True vs 1.0 keeps the pre-existing set add/remove behavior.
        result = DeepDiff({True}, {1.0})
        assert 'set_item_added' in result
        assert 'set_item_removed' in result

    def test_string_change_unchanged(self):
        assert DeepDiff(['a'], ['b']) == {
            'values_changed': {'root[0]': {'new_value': 'b', 'old_value': 'a'}}}

    def test_numeric_value_change_unchanged(self):
        assert DeepDiff([1], [2]) == {
            'values_changed': {'root[0]': {'new_value': 2, 'old_value': 1}}}

    def test_equal_objects_remain_equal(self):
        assert DeepDiff([1, True], [1, True]) == {}
        assert DeepDiff({1, True}, {1, True}) == {}
        assert DeepDiff({'a': [1, True]}, {'a': [1, True]}) == {}

    def test_tuple_uses_ordered_classification(self):
        result = DeepDiff((1,), (True,))
        assert result == {
            'type_changes': {'root[0]': _type_change_entry(1, True, int, bool)}}

    def test_nested_containers_classify_consistently(self):
        list_in_dict = DeepDiff({'s': [1]}, {'s': [True]})
        set_in_dict = DeepDiff({'s': {1}}, {'s': {True}})
        assert set(list_in_dict.keys()) == {'type_changes'}
        assert set(set_in_dict.keys()) == {'type_changes'}


class TestBoolIntPredicate:
    """Unit tests for the shared boundary predicate itself."""

    @pytest.mark.parametrize('x, y', [
        (True, 1), (1, True), (False, 0), (0, False),
    ])
    def test_python_bool_int_pairs_match(self, x, y):
        assert _DeepDiff._is_bool_int_mismatch(x, y) is True

    @pytest.mark.parametrize('x, y', [
        (True, False), (1, 2), (1, 1.0), (True, 1.0),
        (True, '1'), ('a', 'b'), (1, None), (None, True),
    ])
    def test_non_boundary_pairs_do_not_match(self, x, y):
        assert _DeepDiff._is_bool_int_mismatch(x, y) is False

    def test_numpy_integer_is_integer_side(self):
        np = pytest.importorskip('numpy')
        assert _DeepDiff._is_bool_int_mismatch(np.bool_(True), np.int64(1)) is True
        assert _DeepDiff._is_bool_int_mismatch(np.int64(1), True) is True
        # Two booleans, even across the Python/numpy divide, are not a mismatch.
        assert _DeepDiff._is_bool_int_mismatch(np.bool_(True), True) is False

    def test_predicate_is_symmetric_for_bool_int(self):
        assert _DeepDiff._is_bool_int_mismatch(True, 1) == _DeepDiff._is_bool_int_mismatch(1, True)
