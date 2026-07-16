# PlantUML AWS Sprite Reference (Local Library v18)

**Base path**: `~/diagrams/.plantuml-libs/aws-icons-for-plantuml-18.0/dist`

## Compute

| Include | Macro |
|---------|-------|
| `Compute/EC2.puml` | `EC2(alias, "label", "detail")` |
| `Compute/EC2Instance.puml` | `EC2Instance(alias, "label", "detail")` |
| `Compute/Lambda.puml` | `Lambda(alias, "label", "detail")` |
| `Compute/Batch.puml` | `Batch(alias, "label", "detail")` |

## Containers

| Include | Macro |
|---------|-------|
| `Containers/EKSCloud.puml` | `EKSCloud(alias, "label", "detail")` |
| `Containers/ElasticContainerRegistry.puml` | `ElasticContainerRegistry(alias, "label", "detail")` |
| `Containers/ElasticContainerService.puml` | `ElasticContainerService(alias, "label", "detail")` |
| `Containers/Fargate.puml` | `Fargate(alias, "label", "detail")` |

## Database

| Include | Macro |
|---------|-------|
| `Database/RDS.puml` | `RDS(alias, "label", "detail")` |
| `Database/Aurora.puml` | `Aurora(alias, "label", "detail")` |
| `Database/AuroraPostgreSQLInstance.puml` | `AuroraPostgreSQLInstance(alias, "label", "detail")` |
| `Database/DocumentDB.puml` | `DocumentDB(alias, "label", "detail")` |
| `Database/DynamoDB.puml` | `DynamoDB(alias, "label", "detail")` |
| `Database/ElastiCache.puml` | `ElastiCache(alias, "label", "detail")` |

## Networking & Content Delivery

| Include | Macro |
|---------|-------|
| `NetworkingContentDelivery/VirtualPrivateCloud.puml` | `VirtualPrivateCloud(alias, "label", "detail")` |
| `NetworkingContentDelivery/ElasticLoadBalancing.puml` | `ElasticLoadBalancing(alias, "label", "detail")` |
| `NetworkingContentDelivery/CloudFront.puml` | `CloudFront(alias, "label", "detail")` |
| `NetworkingContentDelivery/Route53.puml` | `Route53(alias, "label", "detail")` |

## Application Integration

| Include | Macro |
|---------|-------|
| `ApplicationIntegration/APIGateway.puml` | `APIGateway(alias, "label", "detail")` |
| `ApplicationIntegration/SimpleQueueService.puml` | `SimpleQueueService(alias, "label", "detail")` |
| `ApplicationIntegration/SimpleNotificationService.puml` | `SimpleNotificationService(alias, "label", "detail")` |
| `ApplicationIntegration/EventBridge.puml` | `EventBridge(alias, "label", "detail")` |
| `ApplicationIntegration/MQ.puml` | `MQ(alias, "label", "detail")` |
| `ApplicationIntegration/StepFunctions.puml` | `StepFunctions(alias, "label", "detail")` |

## Storage

| Include | Macro |
|---------|-------|
| `Storage/SimpleStorageService.puml` | `SimpleStorageService(alias, "label", "detail")` |
| `Storage/EFS.puml` | `EFS(alias, "label", "detail")` |
| `Storage/ElasticBlockStore.puml` | `ElasticBlockStore(alias, "label", "detail")` |

## Security, Identity & Compliance

| Include | Macro |
|---------|-------|
| `SecurityIdentityCompliance/Cognito.puml` | `Cognito(alias, "label", "detail")` |
| `SecurityIdentityCompliance/IAMIdentityCenter.puml` | `IAMIdentityCenter(alias, "label", "detail")` |
| `SecurityIdentityCompliance/WAF.puml` | `WAF(alias, "label", "detail")` |
| `SecurityIdentityCompliance/SecretsManager.puml` | `SecretsManager(alias, "label", "detail")` |
| `SecurityIdentityCompliance/CertificateManager.puml` | `CertificateManager(alias, "label", "detail")` |

## Management & Governance

| Include | Macro |
|---------|-------|
| `ManagementGovernance/CloudWatch.puml` | `CloudWatch(alias, "label", "detail")` |
| `ManagementGovernance/SystemsManager.puml` | `SystemsManager(alias, "label", "detail")` |
| `ManagementGovernance/CloudFormation.puml` | `CloudFormation(alias, "label", "detail")` |

## General (actors, clients, servers)

| Include | Macro |
|---------|-------|
| `General/Client.puml` | `Client(alias, "label", "detail")` |
| `General/User.puml` | `User(alias, "label", "detail")` |
| `General/Users.puml` | `Users(alias, "label", "detail")` |
| `General/Traditionalserver.puml` | `Traditionalserver(alias, "label", "detail")` |
| `General/Internet.puml` | `Internet(alias, "label", "detail")` |
| `General/GenericApplication.puml` | `GenericApplication(alias, "label", "detail")` |
| `General/Mobileclient.puml` | `Mobileclient(alias, "label", "detail")` |

## Robotics

| Include | Macro |
|---------|-------|
| `Robotics/Robotics.puml` | `Robotics(alias, "label", "detail")` |

## Groups (VPC/subnet/AZ boundaries)

| Include | Macro |
|---------|-------|
| `Groups/VPC.puml` | `VPCGroup(alias, "label") { ... }` |
| `Groups/AvailabilityZone.puml` | `AvailabilityZoneGroup(alias, "label") { ... }` |
| `Groups/PublicSubnet.puml` | `PublicSubnetGroup(alias, "label") { ... }` |
| `Groups/PrivateSubnet.puml` | `PrivateSubnetGroup(alias, "label") { ... }` |
| `Groups/AWSCloud.puml` | `AWSCloudGroup(alias, "label") { ... }` |
| `Groups/Region.puml` | `RegionGroup(alias, "label") { ... }` |
| `Groups/SecurityGroup.puml` | `SecurityGroupGroup(alias, "label") { ... }` |
| `Groups/AWSAccount.puml` | `AWSAccountGroup(alias, "label") { ... }` |
| `Groups/GenericAlt.puml` | `GenericAltGroup(alias, "label") { ... }` |

## Complete Example

```plantuml
@startuml
!define AWSPuml /Users/hardcode/diagrams/.plantuml-libs/aws-icons-for-plantuml-18.0/dist
!include AWSPuml/AWSCommon.puml
!include AWSPuml/AWSSimplified.puml
!include AWSPuml/Groups/VPC.puml
!include AWSPuml/Groups/PrivateSubnet.puml
!include AWSPuml/Groups/PublicSubnet.puml
!include AWSPuml/Containers/EKSCloud.puml
!include AWSPuml/Database/RDS.puml
!include AWSPuml/Storage/SimpleStorageService.puml
!include AWSPuml/NetworkingContentDelivery/ElasticLoadBalancing.puml

VPCGroup(vpc, "Production VPC") {
  PublicSubnetGroup(pub, "Public Subnet") {
    ElasticLoadBalancing(alb, "ALB", "Application LB")
  }
  PrivateSubnetGroup(priv, "Private Subnet") {
    EKSCloud(eks, "EKS Cluster", "v1.29")
    RDS(rds, "PostgreSQL", "db.r6g.xlarge")
  }
}
SimpleStorageService(s3, "S3 Bucket", "Assets")

alb --> eks : "HTTPS"
eks --> rds : "port 5432"
eks --> s3 : "HTTPS"
@enduml
```
