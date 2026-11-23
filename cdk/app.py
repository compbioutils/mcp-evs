"""Reference AWS CDK (Python) stack for evs-cadsr-mcp (proposal 10.5, SOW-D8).

Topology: ALB (TLS, WAF association optional) -> ECS Fargate service (ARM, >= 2 tasks, uvicorn)
-> ElastiCache (Redis-compatible shared cache) ; Secrets Manager for caDSR credential and EVS
license key; CloudWatch logs; VPC endpoints for AWS services; NAT only for the NCI upstreams.

This is a *reference*: it has not been synthesised or deployed from this repository. Install
`aws-cdk-lib constructs` and run `cdk synth` from this directory. Decisions reserved for NCI
(identity provider, certificate, WAF rules, egress allow-list) are parameters.
"""

from __future__ import annotations

import os

try:
    import aws_cdk as cdk
    from aws_cdk import Duration, Stack
    from aws_cdk import aws_ec2 as ec2
    from aws_cdk import aws_ecs as ecs
    from aws_cdk import aws_ecs_patterns as patterns
    from aws_cdk import aws_elasticache as elasticache
    from aws_cdk import aws_elasticloadbalancingv2 as elbv2
    from aws_cdk import aws_logs as logs
    from aws_cdk import aws_secretsmanager as sm
    from constructs import Construct
except ImportError as exc:  # pragma: no cover - CDK is not a runtime dependency of the server
    raise SystemExit("install aws-cdk-lib and constructs to synthesise this stack") from exc


class EvsCadsrMcpStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, env_name: str, public_host: str, certificate_arn: str, idp_jwks_uri: str, idp_issuer: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = ec2.Vpc(self, "Vpc", max_azs=2, nat_gateways=1)
        for name, service in {
            "SecretsManager": ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            "Logs": ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
            "EcrDocker": ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
            "Ecr": ec2.InterfaceVpcEndpointAwsService.ECR,
        }.items():
            vpc.add_interface_endpoint(name, service=service)

        cadsr_credential = sm.Secret(self, "CadsrCredential", description="caDSR Basic credential user:password (per environment)")
        license_key = sm.Secret(self, "EvsLicenseKey", description="X-EVSRESTAPI-License-Key for Tier-2 targets")

        cache_sg = ec2.SecurityGroup(self, "CacheSg", vpc=vpc, allow_all_outbound=False)
        subnet_group = elasticache.CfnSubnetGroup(self, "CacheSubnets", description="shared cache subnets", subnet_ids=[s.subnet_id for s in vpc.private_subnets])
        cache = elasticache.CfnReplicationGroup(
            self, "SharedCache", replication_group_description="evs-cadsr-mcp shared cache", engine="redis", cache_node_type="cache.t4g.small",
            num_cache_clusters=2, automatic_failover_enabled=True, at_rest_encryption_enabled=True, transit_encryption_enabled=True,
            cache_subnet_group_name=subnet_group.ref, security_group_ids=[cache_sg.security_group_id],
        )

        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, container_insights=True)
        log_group = logs.LogGroup(self, "Logs", retention=logs.RetentionDays.ONE_MONTH)
        image = ecs.ContainerImage.from_asset(os.path.join(os.path.dirname(__file__), "..", ".."), file="deploy/Dockerfile", platform=ecs.Platform.LINUX_ARM64)

        service = patterns.ApplicationLoadBalancedFargateService(
            self, "Service", cluster=cluster, cpu=1024, memory_limit_mib=2048, desired_count=2, public_load_balancer=True,
            runtime_platform=ecs.RuntimePlatform(cpu_architecture=ecs.CpuArchitecture.ARM64, operating_system_family=ecs.OperatingSystemFamily.LINUX),
            certificate=elbv2.ListenerCertificate.from_arn(certificate_arn) if certificate_arn else None,  # type: ignore[arg-type]
            redirect_http=bool(certificate_arn),
            task_image_options=patterns.ApplicationLoadBalancedTaskImageOptions(
                image=image, container_port=8000, log_driver=ecs.LogDrivers.aws_logs(stream_prefix="ecm", log_group=log_group),
                environment={
                    "ECM_PROFILE": "unified", "ECM_PUBLIC_HOST": public_host, "ECM_LOG_JSON": "true",
                    "ECM_ALLOWED_ORIGINS": f'["https://{public_host}"]',
                    "ECM_CACHE_URL": f"rediss://{cache.attr_primary_end_point_address}:{cache.attr_primary_end_point_port}/0",
                    "ECM_AUTH_MODE": "jwt", "ECM_AUTH_JWKS_URI": idp_jwks_uri, "ECM_AUTH_ISSUER": idp_issuer,
                    "ECM_AUTH_AUDIENCE": f"https://{public_host}", "ECM_SCOPE_ENFORCEMENT": "true",
                    "ECM_RATE_LIMIT_PER_MINUTE": "300", "ECM_RATE_LIMIT_BURST": "60", "ECM_AUDIT_SINK": "stdout",
                },
                secrets={"ECM_CADSR_CREDENTIAL": ecs.Secret.from_secrets_manager(cadsr_credential), "ECM_LICENSE_KEY": ecs.Secret.from_secrets_manager(license_key)},
            ),
        )
        service.target_group.configure_health_check(path="/readyz", healthy_http_codes="200", interval=Duration.seconds(30))
        cache_sg.add_ingress_rule(service.service.connections.security_groups[0], ec2.Port.tcp(6379), "server -> shared cache")
        scaling = service.service.auto_scale_task_count(min_capacity=2, max_capacity=8)
        scaling.scale_on_cpu_utilization("Cpu", target_utilization_percent=60)

        cdk.CfnOutput(self, "McpEndpoint", value=f"https://{public_host}/mcp")
        cdk.CfnOutput(self, "AlbDns", value=service.load_balancer.load_balancer_dns_name)


app = cdk.App()
EvsCadsrMcpStack(
    app, "EvsCadsrMcp-dev", env_name="dev",
    public_host=app.node.try_get_context("publicHost") or "evs-cadsr-mcp.dev.example.nih.gov",
    certificate_arn=app.node.try_get_context("certificateArn") or "",
    idp_jwks_uri=app.node.try_get_context("idpJwksUri") or "https://idp.example.nih.gov/.well-known/jwks.json",
    idp_issuer=app.node.try_get_context("idpIssuer") or "https://idp.example.nih.gov/",
)
app.synth()
