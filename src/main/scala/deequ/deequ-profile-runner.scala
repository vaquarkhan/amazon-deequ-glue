// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.text.SimpleDateFormat
import java.util.Date

import com.amazonaws.services.glue.ChoiceOption
import com.amazonaws.services.glue.GlueContext
import com.amazonaws.services.glue.MappingSpec
import com.amazonaws.services.glue.ResolveSpec
import com.amazonaws.services.glue.errors.CallSite
import com.amazonaws.services.glue.util.GlueArgParser
import com.amazonaws.services.glue.util.Job
import com.amazonaws.services.glue.util.JsonOptions
import org.apache.spark.SparkContext
import org.apache.spark.sql.functions._
import org.apache.spark.sql.DataFrame

import scala.collection.JavaConverters._
import org.apache.spark.sql.{Row, SQLContext}
import org.apache.spark.sql.types._


import com.amazon.deequ.profiles.{ColumnProfilerRunner, NumericColumnProfile}

object GlueApp {

  val sc: SparkContext = new SparkContext()
  val glueContext: GlueContext = new GlueContext(sc)
  val spark = glueContext.getSparkSession
  val getYear = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy"))
  val getMonth = LocalDate.now().format(DateTimeFormatter.ofPattern("MM"))
  val getDay = LocalDate.now().format(DateTimeFormatter.ofPattern("dd"))
  val getTimestamp = new SimpleDateFormat("HH-mm-ss").format(new Date)
  import spark.implicits._

  def main(sysArgs: Array[String]) {

    val args = GlueArgParser.getResolvedOptions(sysArgs, Seq("JOB_NAME",
      "glueDatabase",
      "glueTables",
	    "pushDownPredicate",
      "targetBucketName").toArray)

    Job.init(args("JOB_NAME"), glueContext, args.asJava)

    val dbName = args("glueDatabase")
    val tabNames = args("glueTables").split(",").map(_.trim)
	  //val pushDownPredicate = args("pushDownPredicate")
    val pushDownPredicate =args("pushDownPredicate").split(",").map(_.trim)

	  //zip values
    val mapTablePredicate = tabNames zip pushDownPredicate

    //empty df
    var profiler_df: DataFrame = spark.createDataFrame(spark.sparkContext.emptyRDD[Row], StructType(Seq()))

    //for (tabName <- tabNames) {
      for((tabName,predicate) <- mapTablePredicate){
      //println("tabName:=+"+tabName + " -> " +"predicate:="+ predicate)

            if("NONE".equals(predicate)){
              
                  profiler_df = glueContext.getCatalogSource(database = dbName, tableName = tabName,redshiftTmpDir = "", transformationContext = "datasource0").getDynamicFrame().toDF()
                //println("#######################################################")
                //println("profiler_df NONE="+profiler_df.count())
                //profiler_df.show()
                //println("#######################################################")
            }else{
              
                 profiler_df = glueContext.getCatalogSource(database = dbName,tableName = tabName,redshiftTmpDir = "",transformationContext = "datasource0", pushDownPredicate=predicate).getDynamicFrame().toDF()
                 //println("#######################################################")
                 //println("profiler_df NOT NONE="+profiler_df.count())
                 //profiler_df.show()
                 //println("#######################################################")
            }
	
		
        val profileResult = ColumnProfilerRunner()
        .onData(profiler_df)
        .run()

        val profileResultDataset = profileResult.profiles.map {
        case (productName, profile) => (
            productName,
            profile.completeness,
            profile.dataType.toString,
            profile.approximateNumDistinctValues)
        }.toSeq.toDS

        val finalDataset = profileResultDataset
            .withColumnRenamed("_1", "column")
            .withColumnRenamed("_2", "completeness")
            .withColumnRenamed("_3", "inferred_datatype")
            .withColumnRenamed("_4", "approx_distinct_values")
            .withColumn("timestamp", lit(current_timestamp()))

        writeDStoS3(finalDataset, args("targetBucketName"), "profile-results", dbName, tabName, getYear, getMonth, getDay, getTimestamp)
    }

    Job.commit()

  }

  /***
   * Write results data set to S3
   * @param resultDF
   * @param s3Bucket
   * @param s3Prefix
   * @param dbName
   * @param tabName
   * @return
   */
  def writeDStoS3(resultDF: DataFrame, s3Bucket: String, s3Prefix: String, dbName: String, tabName: String, getYear: String, getMonth: String, getDay: String, getTimestamp: String) = {

    resultDF.write.mode("append").parquet(s3Bucket + "/"
      + s3Prefix + "/"
      + "database=" + dbName + "/"
      + "table=" + tabName + "/"
      + "year=" + getYear + "/"
      + "month=" + getMonth + "/"
      + "day=" + getDay + "/"
      + "hour=" + getTimestamp.split("-")(0) + "/"
      + "min=" + getTimestamp.split("-")(1) + "/"
    )
  }
}
