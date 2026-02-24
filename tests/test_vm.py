"""Tests for VM integration."""
import pytest
from unittest.mock import patch, MagicMock
import tempfile
import os

from src.ui_verdict.vm import VMConfig


class TestVMModule:
    """Unit tests for VM module with mocked subprocess."""
    
    def test_vm_config_defaults(self):
        """Test default VM config values."""
        config = VMConfig()
        assert config.name == "ui-test"
        assert config.display == ":99"
        assert config.screen_size == "1920x1080x24"
    
    def test_set_vm(self):
        """Test setting a custom VM name."""
        from src.ui_verdict.vm import set_vm, _config
        original = _config.name
        try:
            set_vm("test-vm")
            assert _config.name == "test-vm"
        finally:
            _config.name = original
    
    @patch('src.ui_verdict.vm._run_in_vm')
    def test_vm_available_success(self, mock_run):
        """Test VM availability check when VM is running."""
        mock_run.return_value = (0, "ok\n", "")
        
        from src.ui_verdict.vm import vm_available
        assert vm_available() is True
        mock_run.assert_called_once()
    
    @patch('src.ui_verdict.vm._run_in_vm')
    def test_vm_available_failure(self, mock_run):
        """Test VM availability check when VM is not running."""
        mock_run.return_value = (1, "", "error")
        
        from src.ui_verdict.vm import vm_available
        assert vm_available() is False
    
    @patch('src.ui_verdict.vm._run_in_vm')
    def test_ensure_xvfb_already_running(self, mock_run):
        """Test Xvfb check when already running."""
        mock_run.side_effect = [
            (0, "1234", ""),  # Xvfb pgrep
            (0, "5678", ""),  # openbox pgrep
            (0, "1234", ""),  # Final verify
        ]
        
        from src.ui_verdict.vm import ensure_xvfb
        assert ensure_xvfb() is True
    
    @patch('src.ui_verdict.vm._run_in_vm')
    def test_ensure_xvfb_starts(self, mock_run):
        """Test Xvfb is started when not running."""
        # Sequence: 
        # 1. Check Xvfb (not running)
        # 2. Start Xvfb
        # 3. Check openbox (not running)
        # 4. Start openbox
        # 5. Final verify Xvfb running
        mock_run.side_effect = [
            (1, "", ""),       # Xvfb not running
            (0, "", ""),       # Start Xvfb
            (1, "", ""),       # openbox not running
            (0, "", ""),       # Start openbox
            (0, "1234", ""),   # Final verify
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
        """Test Xvfb setup in real VM."""
        from src.ui_verdict.vm import ensure_xvfb
        assert ensure_xvfb() is True
    
    def test_real_screenshot(self, check_vm):
        """Test taking a screenshot in real VM."""
        from src.ui_verdict.vm import vm_screenshot, ensure_xvfb
        ensure_xvfb()
        
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        
        try:
            result = vm_screenshot(path)
            assert os.path.exists(result)
            assert os.path.getsize(result) > 0
        finally:
            if os.path.exists(path):
                os.remove(path)
    
    def test_real_key_send(self, check_vm):
        """Test sending a key in real VM."""
        from src.ui_verdict.vm import vm_send_key, ensure_xvfb
        ensure_xvfb()
        
        # Should not raise
        vm_send_key("Return")
    
    def test_real_click(self, check_vm):
        """Test mouse click in real VM."""
        from src.ui_verdict.vm import vm_click, ensure_xvfb
        ensure_xvfb()
        
        # Click in center - should not raise
        vm_click(960, 540)
    
    def test_real_type(self, check_vm):
        """Test typing text in real VM."""
        from src.ui_verdict.vm import vm_type, ensure_xvfb
        ensure_xvfb()
        
        # Should not raise
        vm_type("test")
    
    def test_real_window_info(self, check_vm):
        """Test getting window info from real VM."""
        from src.ui_verdict.vm import vm_window_info, ensure_xvfb
        ensure_xvfb()
        
        info = vm_window_info()
        assert "windows" in info
        assert isinstance(info["windows"], list)
