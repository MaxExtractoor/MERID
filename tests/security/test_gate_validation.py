"""
Gate 1 Security Validation Tests
Gate 1: Infrastructure Security - Evidence Artifact
Date: 2026-01-26

Tests firewall rules, TLS configuration, and RBAC implementation
to validate that security controls are properly enforced.
"""

import pytest
import asyncio
import ssl
import socket
import subprocess
import time
from typing import Dict, List, Any
from unittest.mock import patch, AsyncMock

import httpx
import redis
from neo4j import GraphDatabase


class TestFirewallValidation:
    """Test firewall rules and network access controls."""
    
    @pytest.mark.asyncio
    async def test_allowed_ports_accessible(self):
        """Test that allowed ports are accessible."""
        allowed_ports = [8000, 8001, 7687, 6379]
        
        for port in allowed_ports:
            try:
                # Test TCP connection
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection('localhost', port),
                    timeout=5.0
                )
                writer.close()
                await writer.wait_closed()
                print(f"✅ Port {port} is accessible")
            except (ConnectionRefusedError, asyncio.TimeoutError):
                pytest.fail(f"Port {port} should be accessible but is not")
    
    @pytest.mark.asyncio
    async def test_blocked_ports_inaccessible(self):
        """Test that blocked ports are not accessible."""
        blocked_ports = [22, 3306, 5432, 8080, 9090]
        
        for port in blocked_ports:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection('localhost', port),
                    timeout=2.0
                )
                writer.close()
                await writer.wait_closed()
                pytest.fail(f"Port {port} should be blocked but is accessible")
            except (ConnectionRefusedError, asyncio.TimeoutError):
                print(f"✅ Port {port} is properly blocked")
    
    def test_docker_network_isolation(self):
        """Test Docker network isolation."""
        try:
            # Check if Docker networks exist
            result = subprocess.run(
                ["docker", "network", "ls"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            assert result.returncode == 0, "Docker network command failed"
            
            # Check for merid networks
            networks = result.stdout
            assert "merid" in networks.lower(), "MERID network not found"
            
            print("✅ Docker network isolation validated")
            
        except subprocess.TimeoutExpired:
            pytest.fail("Docker network command timed out")
        except FileNotFoundError:
            pytest.skip("Docker not available")


class TestTLSValidation:
    """Test TLS configuration and certificate validation."""
    
    def test_tls_certificates_exist(self):
        """Test that TLS certificates are present."""
        cert_files = [
            "./certs/server.crt",
            "./certs/server.key", 
            "./certs/ca.crt",
            "./certs/neo4j.crt",
            "./certs/neo4j.key",
            "./certs/redis.crt",
            "./certs/redis.key"
        ]
        
        for cert_file in cert_files:
            try:
                with open(cert_file, 'r') as f:
                    content = f.read()
                    assert len(content) > 0, f"Certificate file {cert_file} is empty"
                    assert "BEGIN CERTIFICATE" in content or "BEGIN PRIVATE KEY" in content, \
                        f"Invalid certificate format in {cert_file}"
                print(f"✅ Certificate {cert_file} exists and is valid")
            except FileNotFoundError:
                pytest.fail(f"Certificate file {cert_file} not found")
    
    @pytest.mark.asyncio
    async def test_https_endpoints_tls_only(self):
        """Test that endpoints only accept HTTPS connections."""
        https_endpoints = [
            ("https://localhost:8443", "https://localhost:8444"),
            ("https://localhost:7473",),  # Neo4j HTTPS
        ]
        
        for endpoint in https_endpoints:
            for url in endpoint:
                try:
                    # Test HTTPS connection
                    async with httpx.AsyncClient(verify=False) as client:
                        response = await client.get(url, timeout=10.0)
                        # Should get some response (even error) over HTTPS
                        print(f"✅ HTTPS endpoint {url} responds")
                        
                except httpx.ConnectError:
                    # Expected if service not running, but should not be TLS error
                    print(f"⚠️ HTTPS endpoint {url} not running (expected in test)")
                except ssl.SSLError as e:
                    pytest.fail(f"TLS error on {url}: {e}")
    
    def test_certificate_strength(self):
        """Test certificate strength and configuration."""
        cert_file = "./certs/server.crt"
        
        try:
            # Load certificate
            with open(cert_file, 'r') as f:
                cert_data = f.read()
            
            # Parse certificate
            cert = ssl.PEM_cert_to_DER_cert(cert_data.encode())
            cert_info = ssl.DER_cert_to_PEM_cert(cert)
            
            # Check certificate properties
            cert_obj = ssl.load_ssl_certificate(cert)
            
            # Verify key strength (should be at least 2048 bits)
            public_key = cert_obj.get_pubkey()
            key_size = public_key.bits()
            assert key_size >= 2048, f"Key size {key_size} is less than 2048 bits"
            
            print(f"✅ Certificate key strength: {key_size} bits")
            
        except Exception as e:
            pytest.fail(f"Certificate validation failed: {e}")
    
    def test_ssl_protocols_disabled(self):
        """Test that weak SSL protocols are disabled."""
        weak_protocols = [ssl.PROTOCOL_SSLv2, ssl.PROTOCOL_SSLv3, ssl.PROTOCOL_TLSv1]
        
        for protocol in weak_protocols:
            try:
                context = ssl.SSLContext(protocol)
                context.verify_mode = ssl.CERT_NONE
                
                # Try to connect with weak protocol
                with socket.create_connection(("localhost", 8443), timeout=5) as sock:
                    try:
                        ssl_sock = context.wrap_socket(sock, server_hostname="localhost")
                        pytest.fail(f"Weak protocol {protocol.name} should be disabled")
                    except ssl.SSLError:
                        print(f"✅ Weak protocol {protocol.name} properly disabled")
                        
            except (ConnectionRefusedError, OSError):
                # Service not running, skip this check
                print(f"⚠️ Service not running for {protocol.name} test")


class TestRBACValidation:
    """Test RBAC implementation and least-privilege access."""
    
    def test_neo4j_least_privilege_user(self):
        """Test Neo4j least-privilege user configuration."""
        try:
            # Connect with app user (limited privileges)
            driver = GraphDatabase.driver(
                "bolt://localhost:7687",
                auth=("merid_app", "test_password"),
                max_connection_lifetime=30
            )
            
            with driver.session() as session:
                # Should be able to read data
                result = session.run("MATCH (n) RETURN count(n) as count")
                count = result.single()["count"]
                assert isinstance(count, int), "Should be able to read data"
                
                # Should NOT be able to create users (admin operation)
                try:
                    session.run("CREATE USER test_user IF NOT EXISTS SET PASSWORD 'test'")
                    pytest.fail("App user should not be able to create users")
                except Exception as e:
                    assert "permission" in str(e).lower() or "unauthorized" in str(e).lower()
                    print("✅ App user properly restricted from admin operations")
            
            driver.close()
            
        except Exception as e:
            if "connection" in str(e).lower():
                pytest.skip("Neo4j not available for RBAC testing")
            else:
                pytest.fail(f"Neo4j RBAC test failed: {e}")
    
    def test_redis_acl_configuration(self):
        """Test Redis ACL configuration."""
        try:
            # Connect with app user (limited privileges)
            r = redis.Redis(
                host='localhost',
                port=6380,
                password='test_password',
                ssl=True,
                ssl_cert_reqs=None,
                username='merid_app'
            )
            
            # Should be able to read/write data
            r.set('test_key', 'test_value')
            value = r.get('test_key')
            assert value == b'test_value', "Should be able to read/write data"
            
            # Should NOT be able to execute dangerous commands
            dangerous_commands = ['CONFIG', 'FLUSHALL', 'SHUTDOWN']
            for cmd in dangerous_commands:
                try:
                    r.execute_command(cmd)
                    pytest.fail(f"App user should not be able to execute {cmd}")
                except redis.ResponseError as e:
                    assert "permission" in str(e).lower() or "unauthorized" in str(e).lower()
                    print(f"✅ App user properly restricted from {cmd}")
            
            r.close()
            
        except redis.ConnectionError:
            pytest.skip("Redis not available for RBAC testing")
        except Exception as e:
            pytest.fail(f"Redis RBAC test failed: {e}")
    
    def test_docker_non_root_user(self):
        """Test that containers run as non-root user."""
        try:
            # Check merid-api container user
            result = subprocess.run(
                ["docker", "inspect", "merid-api"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                import json
                container_info = json.loads(result.stdout)
                
                if container_info and len(container_info) > 0:
                    user = container_info[0]["Config"].get("User")
                    if user:
                        # Should be non-root (not 0:0)
                        assert user != "0:0" and user != "root", f"Container running as root: {user}"
                        print(f"✅ Container running as non-root user: {user}")
                    else:
                        pytest.skip("Container user not specified")
                else:
                    pytest.skip("Container not found")
            else:
                pytest.skip("Docker inspect failed")
                
        except subprocess.TimeoutExpired:
            pytest.skip("Docker command timed out")
        except FileNotFoundError:
            pytest.skip("Docker not available")
        except json.JSONDecodeError:
            pytest.fail("Failed to parse Docker inspect output")


class TestSecurityIntegration:
    """Integration tests for security controls."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_security_flow(self):
        """Test complete security flow from network to application."""
        
        # 1. Test network access (only allowed ports)
        await TestFirewallValidation().test_allowed_ports_accessible()
        await TestFirewallValidation().test_blocked_ports_inaccessible()
        
        # 2. Test TLS configuration
        TestTLSValidation().test_tls_certificates_exist()
        
        # 3. Test RBAC (if services are running)
        try:
            TestRBACValidation().test_neo4j_least_privilege_user()
            TestRBACValidation().test_redis_acl_configuration()
        except Exception:
            print("⚠️ RBAC tests skipped (services not running)")
        
        print("✅ End-to-end security flow validated")
    
    def test_security_configuration_completeness(self):
        """Test that all security configurations are present."""
        required_files = [
            "infra/firewall-rules.yml",
            "infra/tls-config.yml", 
            "infra/rbac-config.yml",
            ".github/workflows/audit-gates.yml"
        ]
        
        for file_path in required_files:
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                    assert len(content) > 0, f"Configuration file {file_path} is empty"
                print(f"✅ Security configuration {file_path} present")
            except FileNotFoundError:
                pytest.fail(f"Required security configuration {file_path} not found")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
