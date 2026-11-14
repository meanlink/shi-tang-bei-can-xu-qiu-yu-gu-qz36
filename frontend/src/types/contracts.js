/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,withdrawn:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean,withdrawn:boolean}} ReportSchedule */
/** @typedef {{id:number,dataset_id:number,reason:string,status:'processing'|'completed'|'failed',affected:Object,error:string,created_at:number,finished_at:number?}} Withdrawal */
export {};
