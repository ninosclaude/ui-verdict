"""Tests for VM integration module."""
import pytest
import os
from unittest.mock import patch, MagicMock


class TestVMModule:
    """Test VM module functions."""
    
    def test_vm_config_defaults(self):
        """Test default VM configuration."""
        from src.ui_verdict.vm import _config
        
        assert _config.name == "ui-test"
        assert _config.display == ":99"
        assert _config.screen_size == "1920x1080x24"
    
    def test_set_vm(self):
        """Test setting VM name."""
        from src.ui_verdict.vm import set_vm, _config
        
        original = _config.name
        set_vm("test-vm")
        assert _config.name == "test-vm"
        _config.name = original  # Restore
    
    @patch('src.ui_verdict.vm.subprocess.run')
    def test_vm_available_success(self, mock_run):
        """Test VM availability check when successful."""
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        
        from src.ui_verdict.vm import vm_available
        assert vm_available() is True
    
    @patch('src.ui_verdict.vm.subprocess.run')
    def test_vm_available_failure(self, mock_run):
        """Test VM availability check when VM is down."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        
        from src.ui_verdict.vm import vm_available
        assert vm_available() is False
    
    @patch('src.ui_verdict.vm._run_in_vm')
    def test_ensure_xvfb_already_running(self, mock_run):
        """Test Xvfb check when already running."""
        mock_run.return_value = (0, "1234", "")  # PID returned
        
        from src.ui_verdict.vm import ensure_xvfb
        assert ensure_xvfb() is True
    
    @patch('src.ui_verdict.vm._run_in_vm')
    def test_ensure_xvfb_starts(self, mock_run):
        """Test Xvfb is started when not running."""
        # First call: not running, second call: start, third call: verify
        mock_run.side_effect = [
            (1, "", ""),  # Not running
            (0, "", ""),  # Start command
            (0, "1234", ""),  # Verify running
        ]
        
        from src.ui_verdict.vm import ensure_xvfb
        import time
        with patch.object(time, 'sleep'):  # Skip sleep
            assert ensure_xvfb() is True


class TestVMIntegration:
    """Integration tests - require actual VM to be running."""
    
    @pytest.fixture
    def check_vm(self):
        """Skip if VM is not available."""
        from src.ui_verdict.vm import vm_available
        if not vm_available():
            pytest.skip("VM 'ui-test' is not running")
    
    def test_real_vm_available(self, check_vm):
        """Test real VM is accessible."""
        from src.ui_verdict.vm import vm_available
        assert vm_available() is True
    
    def test_real_xvfb(self, check_vm):
        """Test real Xvfb can be started."""
        from src.ui_verdict.vm import ensure_xvfb
        assert ensure_xvfb() is True
    
    def test_real_screenshot(self, check_vm):
        """Test taking a real screenshot."""
        from src.ui_verdict.vm import ensure_xvfb, vm_screenshot
        
        ensure_xvfb()
        path = vm_screenshot()
        
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        
        # Cleanup
        os.unlink(path)
    
    def test_real_key_send(self, check_vm):
        """Test sending a key to VM."""
        from src.ui_verdict.vm import ensure_xvfb, vm_send_key
        
        ensure_xvfb()
        # Should not raise
        vm_send_key("a")
    
    def test_real_click(self, check_vm):
        """Test sending a click to VM."""
        from src.ui_verdict.vm import ensure_xvfb, vm_click
        
        ensure_xvfb()
        # Should not raise
        vm_click(100, 100)
