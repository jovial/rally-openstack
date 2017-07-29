# Copyright 2014: Mirantis Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import ddt
import mock

from rally import exceptions
from rally.task import context
from tests.unit import fakes
from tests.unit import test


@ddt.ddt
class BaseContextTestCase(test.TestCase):

    @ddt.data({"config": {"bar": "spam"}, "expected": {"bar": "spam"}},
              {"config": {"bar": "spam"}, "expected": {"bar": "spam"}},
              {"config": {}, "expected": {}},
              {"config": None, "expected": None},
              {"config": 42, "expected": 42},
              {"config": "foo str", "expected": "foo str"},
              {"config": [], "expected": ()},
              {"config": [11, 22, 33], "expected": (11, 22, 33)})
    @ddt.unpack
    def test_init(self, config, expected):
        ctx = {"config": {"foo": 42, "fake": config}, "task": "foo_task"}
        ins = fakes.FakeContext(ctx)
        self.assertEqual(expected, ins.config)
        self.assertEqual("foo_task", ins.task)
        self.assertEqual(ctx, ins.context)

    def test_init_with_default_config(self):
        @context.configure(name="foo", order=1)
        class FooContext(fakes.FakeContext):
            DEFAULT_CONFIG = {"alpha": "beta", "delta": "gamma"}

        self.addCleanup(FooContext.unregister)

        ctx = {"config": {"foo": {"ab": "cd"}, "bar": 42}, "task": "foo_task"}
        ins = FooContext(ctx)
        self.assertEqual({"ab": "cd", "alpha": "beta", "delta": "gamma"},
                         ins.config)

    def test_init_empty_context(self):
        ctx0 = {
            "task": mock.MagicMock(),
            "config": {"fake": {"foo": 42}}
        }
        ctx = fakes.FakeContext(ctx0)
        self.assertEqual(ctx0["config"]["fake"], ctx.config)
        self.assertEqual(ctx0["task"], ctx.task)
        self.assertEqual(ctx0, ctx.context)

    @ddt.data(({"test": 2}, True), ({"nonexisting": 2}, False))
    @ddt.unpack
    def test_validate(self, config, valid):
        results = context.Context.validate("fake", None, None, config)
        if valid:
            self.assertEqual(results, [])
        else:
            self.assertEqual(1, len(results))

    def test_setup_is_abstract(self):

        @context.configure("test_abstract_setup", 0)
        class A(context.Context):

            def cleanup(self):
                pass

        self.addCleanup(A.unregister)
        self.assertRaises(TypeError, A)

    def test_cleanup_is_abstract(self):

        @context.configure("test_abstract_cleanup", 0)
        class A(context.Context):

            def setup(self):
                pass

        self.addCleanup(A.unregister)
        self.assertRaises(TypeError, A)

    def test_with_statement(self):
        ctx0 = {
            "task": mock.MagicMock()
        }
        ctx = fakes.FakeContext(ctx0)
        ctx.setup = mock.MagicMock()
        ctx.cleanup = mock.MagicMock()

        with ctx as entered_ctx:
            self.assertEqual(ctx, entered_ctx)

        ctx.cleanup.assert_called_once_with()

    def test_get_owner_id_from_task(self):
        ctx = {"config": {"fake": {"test": 10}}, "task": {"uuid": "task_uuid"}}
        ins = fakes.FakeContext(ctx)
        self.assertEqual("task_uuid", ins.get_owner_id())

    def test_get_owner_id(self):
        ctx = {"config": {"fake": {"test": 10}}, "task": {"uuid": "task_uuid"},
               "owner_id": "foo_uuid"}
        ins = fakes.FakeContext(ctx)
        self.assertEqual("foo_uuid", ins.get_owner_id())


class ContextManagerTestCase(test.TestCase):
    @mock.patch("rally.task.context.ContextManager._get_sorted_context_lst")
    def test_setup(self, mock__get_sorted_context_lst):
        foo_context = mock.MagicMock()
        bar_context = mock.MagicMock()
        mock__get_sorted_context_lst.return_value = [foo_context, bar_context]

        ctx_object = {"config": {"a": [], "b": []}}

        manager = context.ContextManager(ctx_object)
        result = manager.setup()

        self.assertEqual(result, ctx_object)
        foo_context.setup.assert_called_once_with()
        bar_context.setup.assert_called_once_with()

    def test_get_sorted_context_lst(self):

        @context.configure("foo", order=1)
        class A(context.Context):

            def setup(self):
                pass

            def cleanup(self):
                pass

        @context.configure("foo", platform="foo", order=0)
        class B(A):
            pass

        @context.configure("boo", platform="foo", order=2)
        class C(A):
            pass

        self.addCleanup(A.unregister)
        self.addCleanup(B.unregister)
        self.addCleanup(C.unregister)

        ctx_obj = {"config": {"foo@default": [], "boo": [], "foo@foo": []}}
        ctx_insts = context.ContextManager(ctx_obj)._get_sorted_context_lst()
        self.assertEqual(3, len(ctx_insts))
        self.assertIsInstance(ctx_insts[0], B)
        self.assertIsInstance(ctx_insts[1], A)
        self.assertIsInstance(ctx_insts[2], C)

    @mock.patch("rally.task.context.Context.get_all")
    def test_get_sorted_context_lst_fails(self, mock_context_get_all):

        ctx_object = {"config": {"foo": "bar"}}

        mock_context_get_all.return_value = []
        manager = context.ContextManager(ctx_object)

        self.assertRaises(exceptions.PluginNotFound,
                          manager._get_sorted_context_lst)

        mock_context_get_all.assert_called_once_with(
            name="foo", platform=None, allow_hidden=True)

    def test_cleanup(self):
        mock_obj = mock.MagicMock()

        @context.configure("a", platform="foo", order=1)
        class A(context.Context):

            def setup(self):
                pass

            def cleanup(self):
                mock_obj("a@foo")

        self.addCleanup(A.unregister)

        @context.configure("b", platform="foo", order=2)
        class B(context.Context):

            def setup(self):
                pass

            def cleanup(self):
                mock_obj("b@foo")

        ctx_object = {"config": {"a@foo": [], "b@foo": []}}
        context.ContextManager(ctx_object).cleanup()
        mock_obj.assert_has_calls([mock.call("b@foo"), mock.call("a@foo")])

    @mock.patch("rally.task.context.LOG.exception")
    def test_cleanup_exception(self, mock_log_exception):
        mock_obj = mock.MagicMock()

        @context.configure("a", platform="foo", order=1)
        class A(context.Context):

            def setup(self):
                pass

            def cleanup(self):
                mock_obj("a@foo")
                raise Exception("So Sad")

        self.addCleanup(A.unregister)
        ctx_object = {"config": {"a@foo": []}}
        context.ContextManager(ctx_object).cleanup()
        mock_obj.assert_called_once_with("a@foo")
        mock_log_exception.assert_called_once_with(
            "Context a@foo.cleanup() failed.")

    @mock.patch("rally.task.context.ContextManager.cleanup")
    @mock.patch("rally.task.context.ContextManager.setup")
    def test_with_statement(
            self, mock_context_manager_setup, mock_context_manager_cleanup):
        with context.ContextManager(mock.MagicMock()):
            mock_context_manager_setup.assert_called_once_with()
            mock_context_manager_setup.reset_mock()
            self.assertFalse(mock_context_manager_cleanup.called)
        self.assertFalse(mock_context_manager_setup.called)
        mock_context_manager_cleanup.assert_called_once_with()

    @mock.patch("rally.task.context.ContextManager.cleanup")
    @mock.patch("rally.task.context.ContextManager.setup")
    def test_with_statement_exception_during_setup(
            self, mock_context_manager_setup, mock_context_manager_cleanup):
        mock_context_manager_setup.side_effect = Exception("abcdef")

        try:
            with context.ContextManager(mock.MagicMock()):
                pass
        except Exception:
            pass
        finally:
            mock_context_manager_setup.assert_called_once_with()
            mock_context_manager_cleanup.assert_called_once_with()
