# Service Mesh

## What is a Service mesh?

A service mesh is an infrastructure layer that handles security controls, observability, and traffic management for a microservice application.  Generally, a goal of a service mesh is to add this functionality *without the microservices knowing about it*, enabling developers to separate these concerns from their applications.  

Specific examples of how a service mesh can help your microservice application include:
* gaining visibility into the traffic flow of your application, for example to trace network requests or identify routing issues
* implementing access controls, for example blocking all incoming traffic to `MyApp-backend` except `GET` requests coming from `MyApp-frontend`

Some examples of service meshes include:

* [Istio](./istio.md)
* Cilium
* Consol
